"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be walked into a specific state across
many API calls (make a truck OPERABLE, reserve+arrive a booking, open+capture an order,
etc.). These helpers encapsulate those preambles so tests focus on assertions.

Every helper uses get_success_data() (lenient validator) so a setup failure surfaces as a
clear "Setup failed" rather than a confusing assertion failure. Because the harness restarts
the server (empty DB) before every test, each helper builds its preconditions from scratch.

Identity threading: after creating the entity_backed OperatorTruck, every ownership-gated
call uses make_operator_truck_headers(truck["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_commissary_payload, create_truck_payload, issue_health_permit_payload,
    create_spot_payload, create_event_payload, create_booking_payload,
    create_menu_item_payload, create_prep_batch_payload, create_staff_shift_payload,
    create_utility_log_payload, create_order_payload, create_order_line_payload,
    settle_payload, capture_payment_payload, set_clock_payload,
)
from .test_users import TEST_USERS, make_operator_truck_headers


DISPATCHER = TEST_USERS["dispatcher_headers"]
HEALTH_INSPECTOR = TEST_USERS["health_inspector_headers"]
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Clock control ──────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance (or set) the server clock. Runs permit-expiry and no-show sweeps."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), PLATFORM_ADMIN))


# ─── Tier 1: Primitive creators ─────────────────────────────────────────────

def create_commissary(**overrides):
    return get_success_data(api_client.create_commissary(create_commissary_payload(**overrides), DISPATCHER))


def create_truck(commissary_id, **overrides):
    return get_success_data(api_client.create_truck(create_truck_payload(commissary_id, **overrides), DISPATCHER))


def issue_permit(truck_id, **overrides):
    return get_success_data(api_client.issue_health_permit(issue_health_permit_payload(truck_id, **overrides), HEALTH_INSPECTOR))


def create_spot(**overrides):
    return get_success_data(api_client.create_spot(create_spot_payload(**overrides), DISPATCHER))


def create_event(starts_at, ends_at, **overrides):
    return get_success_data(api_client.create_event(create_event_payload(starts_at, ends_at, **overrides), DISPATCHER))


def add_propane(truck_id, psi):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.create_utility_log(
        create_utility_log_payload(truck_id, "PROPANE", propane_psi_after=psi), h))


def add_generator(truck_id, hours):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.create_utility_log(
        create_utility_log_payload(truck_id, "GENERATOR", generator_delta_hours=hours), h))


def add_shift(truck_id, role, shift_start, shift_end, staff_name=None):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.create_staff_shift(
        create_staff_shift_payload(truck_id, role, shift_start, shift_end, staff_name=staff_name), h))


def add_menu_item(truck_id, **overrides):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.create_menu_item(create_menu_item_payload(truck_id, **overrides), h))


def add_prep_batch(truck_id, menu_item_id, units_made=10):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.create_prep_batch(
        create_prep_batch_payload(truck_id, menu_item_id, units_made), h))


def read_truck_version(truck_id):
    truck = get_success_data(api_client.get_truck(truck_id, DISPATCHER))
    return truck["version"]


# ─── Tier 2: Operability progression ────────────────────────────────────────

def make_operable_truck(day_iso, clock_iso, *, psi=50, with_cook=True, with_driver=True,
                        shift_start=None, shift_end=None):
    """Walk a truck up to OPERABLE (or RESTRICTED if a soft gate is intentionally omitted).

    Creates: commissary -> set clock -> truck -> ACTIVE permit -> propane(psi) ->
    optional DRIVER shift -> optional COOK shift. Shifts span the whole day by default so
    they cover `clock_iso`.

    Returns dict with keys: commissary, truck, permit (and the operability the truck now holds).
    """
    set_clock(clock_iso)
    commissary = create_commissary()
    truck = create_truck(commissary["id"])
    permit = issue_permit(truck["id"])
    add_propane(truck["id"], psi)
    s_start = shift_start or f"{day_iso}T08:00:00.000Z"
    s_end = shift_end or f"{day_iso}T23:59:00.000Z"
    if with_driver:
        add_shift(truck["id"], "DRIVER", s_start, s_end, staff_name="Dee")
    if with_cook:
        add_shift(truck["id"], "COOK", s_start, s_end, staff_name="Coe")
    fresh = get_success_data(api_client.get_truck(truck["id"], DISPATCHER))
    return {"commissary": commissary, "truck": fresh, "permit": permit}


def reserve_booking(truck_id, spot_id, event_id, window_start, window_end):
    """Reserve a booking using the truck's current version for the OCC check."""
    h = make_operator_truck_headers(truck_id)
    version = read_truck_version(truck_id)
    return get_success_data(api_client.create_booking(
        create_booking_payload(truck_id, spot_id, event_id, window_start, window_end, version), h))


def setup_reserved_booking(day_iso, *, clock_iso=None, reservation_fee_cents=2500,
                           window_start=None, window_end=None,
                           event_start=None, event_end=None, capacity=2, psi=50,
                           with_cook=True):
    """OPERABLE (or RESTRICTED) truck holding one RESERVED booking.

    Returns dict: commissary, truck, permit, spot, event, booking.
    """
    clock_iso = clock_iso or f"{day_iso}T18:00:00.000Z"
    ctx = make_operable_truck(day_iso, clock_iso, psi=psi, with_cook=with_cook)
    spot = create_spot(concurrent_capacity=capacity, reservation_fee_cents=reservation_fee_cents)
    event = create_event(event_start or f"{day_iso}T17:00:00.000Z",
                         event_end or f"{day_iso}T22:00:00.000Z")
    booking = reserve_booking(
        ctx["truck"]["id"], spot["id"], event["id"],
        window_start or f"{day_iso}T17:30:00.000Z",
        window_end or f"{day_iso}T21:00:00.000Z")
    ctx.update({"spot": spot, "event": event, "booking": booking})
    return ctx


def setup_arrived_booking(day_iso, **overrides):
    """OPERABLE truck with a booking walked through to ARRIVED. Returns same dict as
    setup_reserved_booking, with booking now ARRIVED."""
    ctx = setup_reserved_booking(day_iso, **overrides)
    h = make_operator_truck_headers(ctx["truck"]["id"])
    ctx["booking"] = get_success_data(api_client.arrive_booking(ctx["booking"]["id"], h))
    return ctx


# ─── Tier 3: Order lifecycle ────────────────────────────────────────────────

def open_order(truck_id, booking_id):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.create_order(create_order_payload(booking_id), h))


def add_line(truck_id, order_id, menu_item_id, quantity):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.create_order_line(
        create_order_line_payload(order_id, menu_item_id, quantity), h))


def authorize(truck_id, order_id):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.authorize_payment(order_id, h))


def capture(truck_id, order_id, **overrides):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.capture_payment(order_id, h, capture_payment_payload(**overrides)))


def settle(truck_id, order_id, discount_code="NONE"):
    h = make_operator_truck_headers(truck_id)
    return get_success_data(api_client.settle_order(order_id, h, settle_payload(discount_code)))


def setup_captured_order(day_iso, *, line_specs, item_price_cents=300, prepared_units=30,
                         tip_cents=None, **booking_overrides):
    """OPERABLE truck, ARRIVED booking, one menu item with prepared inventory, an OPEN order
    whose payment is CAPTURED, with the given order lines added.

    line_specs: list of integer quantities, one per line (all of the single item).
    Returns dict: commissary, truck, permit, spot, event, booking, item, order.
    """
    ctx = setup_arrived_booking(day_iso, **booking_overrides)
    truck_id = ctx["truck"]["id"]
    item = add_menu_item(truck_id, sku="ITEM", unit_price_cents=item_price_cents, par_units=prepared_units)
    add_prep_batch(truck_id, item["id"], units_made=prepared_units)
    order = open_order(truck_id, ctx["booking"]["id"])
    for qty in line_specs:
        add_line(truck_id, order["id"], item["id"], qty)
    authorize(truck_id, order["id"])
    cap_overrides = {} if tip_cents is None else {"tip_cents": tip_cents}
    order = capture(truck_id, order["id"], **cap_overrides)
    ctx.update({"item": item, "order": order})
    return ctx
