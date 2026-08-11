"""Composite setup helpers.

Every test runs against a freshly restarted server with an empty database, so
these helpers build complete preconditions (plan -> merchant -> cycle ->
shopper -> order -> fulfilment -> inspection -> settlement) using only
PRD-declared endpoints. Setup calls go through get_success_data() so failures
surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    append_ledger_entry_payload,
    change_method_payload,
    confirm_dropoff_payload,
    create_billing_cycle_payload,
    create_carrier_route_payload,
    create_consolidation_tote_payload,
    create_courier_zone_payload,
    create_dropoff_location_payload,
    create_exception_case_payload,
    create_locker_slot_payload,
    create_merchant_account_payload,
    create_pickup_appointment_payload,
    create_return_item_line,
    create_return_order_payload,
    create_shopper_payload,
    create_slot_reservation_payload,
    create_subscription_plan_payload,
    flag_discrepancy_payload,
    inspect_item_payload,
    issue_label_payload,
    reschedule_pickup_payload,
    resolve_exception_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_location_operator_headers,
    make_shopper_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ADMIN2 = TEST_USERS["platform_admin2_headers"]
AGENT = TEST_USERS["support_agent_headers"]
AGENT2 = TEST_USERS["support_agent2_headers"]
DISPATCHER = TEST_USERS["carrier_dispatcher_headers"]


# --- Tier 1: commercial spine (plan -> merchant -> cycle -> shopper) ---------

def create_plan(**overrides) -> dict:
    """Create a plan in DRAFT. Returns the SubscriptionPlan."""
    return get_success_data(
        api_client.create_subscription_plan(create_subscription_plan_payload(**overrides), ADMIN)
    )


def create_published_plan(**overrides) -> dict:
    """Create + publish a plan. Returns the PUBLISHED SubscriptionPlan."""
    plan = create_plan(**overrides)
    return get_success_data(api_client.publish_subscription_plan(plan["id"], ADMIN))


def create_merchant(plan_id, **overrides) -> dict:
    """Create a merchant (ACTIVE, ledger 0) on a PUBLISHED plan."""
    return get_success_data(
        api_client.create_merchant_account(
            create_merchant_account_payload(plan_id, **overrides), ADMIN
        )
    )


def create_billing_cycle(merchant_id, **overrides) -> dict:
    """Open a billing cycle for the merchant (default window covers the
    default logical clock 2026-05-01T00:00:00Z)."""
    return get_success_data(
        api_client.create_billing_cycle(
            merchant_id, create_billing_cycle_payload(**overrides), ADMIN
        )
    )


def create_shopper(email, full_name="Test Shopper", **overrides) -> dict:
    """Register a shopper. Self-service registration uses the Shopper role;
    for self-registration the returned id is the caller's own, so we build
    entity-backed headers from the response (PRD §2.1)."""
    shopper = get_success_data(
        api_client.create_shopper(
            create_shopper_payload(email=email, full_name=full_name, **overrides),
            TEST_USERS["shopper_headers"],
        )
    )
    return shopper


def create_zone(**overrides) -> dict:
    """Create a courier zone. Returns the CourierZone."""
    return get_success_data(
        api_client.create_courier_zone(create_courier_zone_payload(**overrides), ADMIN)
    )


def set_clock(to_iso8601: str) -> dict:
    """Advance the server's logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))


def run_sweep() -> dict:
    """Run the expiry sweep at the current logical instant (PRD §2.5)."""
    return get_success_data(api_client.run_sweep(ADMIN))


def setup_commercial_spine(plan_overrides=None, legal_name="Test Merchant",
                           shopper_email="shopper@x.com",
                           with_cycle=True, with_zone=False):
    """Published plan + ACTIVE merchant + (optional) OPEN cycle + shopper
    (+ optional courier zone).

    Returns a dict: {plan, merchant, cycle?, shopper, shopper_headers, zone?}.
    The cycle (when present) uses the default window, which covers the
    default logical clock 2026-05-01T00:00:00Z.
    """
    plan = create_published_plan(**(plan_overrides or {}))
    merchant = create_merchant(plan["id"], legal_name=legal_name)
    result = {"plan": plan, "merchant": merchant}
    if with_cycle:
        result["cycle"] = create_billing_cycle(merchant["id"])
    shopper = create_shopper(shopper_email)
    result["shopper"] = shopper
    result["shopper_headers"] = make_shopper_headers(shopper["id"])
    if with_zone:
        result["zone"] = create_zone()
    return result


# --- Tier 2: return order creation --------------------------------------------

def create_order(spine, method="COUNTER_DROP", items=None, **overrides) -> dict:
    """Create a return order as the spine's shopper (ownership-threaded)."""
    payload = create_return_order_payload(
        spine["shopper"]["id"], spine["merchant"]["id"], method=method,
        items=items, **overrides,
    )
    return get_success_data(
        api_client.create_return_order(payload, spine["shopper_headers"])
    )


def get_order(order_id, headers=None) -> dict:
    return get_success_data(api_client.get_return_order(order_id, headers or ADMIN))


def list_order_items(order_id, headers=None) -> list:
    """Return the order's items as a plain list (data array of the envelope)."""
    return get_success_data(api_client.list_return_order_items(order_id, headers or ADMIN))


def get_projection(order_id, headers=None) -> dict:
    return get_success_data(api_client.get_refund_projection(order_id, headers or ADMIN))


def get_ledger(order_id, headers=None) -> list:
    return get_success_data(api_client.list_refund_ledger(order_id, headers or ADMIN))


# --- Tier 2: locations / slots / routes / totes --------------------------------

def create_location(name="Test Location", kind="COUNTER", activate=True,
                    **overrides) -> dict:
    """Create a dropoff location; activates it by default (OPERATIONAL)."""
    location = get_success_data(
        api_client.create_dropoff_location(
            create_dropoff_location_payload(name=name, kind=kind, **overrides), ADMIN
        )
    )
    if activate:
        location = get_success_data(api_client.activate_location(location["id"], ADMIN))
    return location


def create_slot(location_id, size_class="XL") -> dict:
    """Add a locker slot to a location. Returns the LockerSlot (EMPTY)."""
    return get_success_data(
        api_client.create_locker_slot(
            location_id, create_locker_slot_payload(size_class=size_class), ADMIN
        )
    )


def create_route(location_id, **overrides) -> dict:
    """Create a PLANNED carrier route from the given origin location."""
    return get_success_data(
        api_client.create_carrier_route(
            create_carrier_route_payload(location_id, **overrides), DISPATCHER
        )
    )


def create_tote(route_id, location_id) -> dict:
    """Create a FILLING tote at the route's origin location (operator-owned)."""
    return get_success_data(
        api_client.create_consolidation_tote(
            create_consolidation_tote_payload(route_id, location_id),
            make_location_operator_headers(location_id),
        )
    )


# --- Tier 3: label / drop-off / pickup lifecycle shortcuts ---------------------

def issue_label(order, label_type="CARRIER_LABEL", headers=None):
    """Issue a label against the order at its current version. Returns the
    new Label."""
    headers = headers or make_shopper_headers(order["shopper_id"])
    return get_success_data(
        api_client.issue_label(
            order["id"],
            issue_label_payload(label_type, order["version"]),
            headers,
        )
    )


def confirm_dropoff(order_id, location_id):
    """Operator confirms a counter drop-off (ownership-threaded)."""
    return get_success_data(
        api_client.confirm_dropoff(
            order_id, confirm_dropoff_payload(location_id),
            make_location_operator_headers(location_id),
        )
    )


def create_counter_order_dropped_off(spine, location, items=None, **overrides):
    """COUNTER_DROP order -> label issued -> confirmed drop-off at the given
    location. Returns the order snapshot in DROPPED_OFF status."""
    order = create_order(spine, method="COUNTER_DROP", items=items, **overrides)
    issue_label(order, label_type="CARRIER_LABEL")
    return confirm_dropoff(order["id"], location["id"])


def reserve_slot(order, slot, shopper_headers):
    """Create a HELD slot reservation (auto-issues the QR label, order ->
    LABEL_ISSUED). Returns the SlotReservation."""
    return get_success_data(
        api_client.create_slot_reservation(
            create_slot_reservation_payload(order["id"], slot["id"]), shopper_headers
        )
    )


def book_pickup(order, zone, shopper_headers=None, **overrides) -> dict:
    """Book a pickup appointment (order stays INITIATED, QR label
    auto-issued -> order LABEL_ISSUED). Returns the PickupAppointment."""
    return get_success_data(
        api_client.create_pickup_appointment(
            create_pickup_appointment_payload(order["id"], zone["id"], **overrides),
            shopper_headers or make_shopper_headers(order["shopper_id"]),
        )
    )


def drive_pickup_collect(appointment_id):
    """start -> collect. Order advances to IN_TRANSIT; label consumed."""
    get_success_data(api_client.start_pickup(appointment_id, ADMIN))
    return get_success_data(api_client.collect_pickup(appointment_id, ADMIN))


def receive_order(order_id, headers=None):
    """Receive an IN_TRANSIT order into INSPECTING."""
    return get_success_data(api_client.receive_return_order(order_id, headers or ADMIN))


def fulfill_order_via_pickup(spine, items=None, **overrides):
    """Full pickup fulfilment to INSPECTING: order -> appointment -> start ->
    collect -> receive. Returns (order, items_list)."""
    order = create_order(spine, method="HOME_PICKUP", boxless=True, items=items,
                         **overrides)
    appointment = book_pickup(order, spine["zone"])
    drive_pickup_collect(appointment["id"])
    receive_order(order["id"])
    return order, list_order_items(order["id"])


def inspect_item(item_id, condition, headers=None, **overrides):
    return get_success_data(
        api_client.inspect_return_item(
            item_id, inspect_item_payload(condition, **overrides), headers or ADMIN
        )
    )


def fulfill_order_to_refund_posted(spine, items=None, inspect_condition="NEW",
                                   **overrides):
    """Full lifecycle to REFUND_POSTED via the pickup path: fulfil, then
    inspect every item with the same condition. Returns (order, projection)."""
    order, items = fulfill_order_via_pickup(spine, items=items, **overrides)
    for item in items:
        inspect_item(item["id"], inspect_condition)
    return get_order(order["id"]), get_projection(order["id"])


# --- Tier 3: exception helpers ---------------------------------------------------

def open_exception(order_id, kind, note="opened", return_item_id=None,
                   opener_headers=None):
    """Open an exception case (SupportAgent by default). Returns the case."""
    payload = create_exception_case_payload(
        order_id, kind, note, return_item_id=return_item_id
    )
    return get_success_data(
        api_client.create_exception_case(payload, opener_headers or AGENT)
    )


def start_investigation(case_id, headers=None):
    return get_success_data(
        api_client.start_investigation(case_id, headers or AGENT)
    )


def resolve_exception(case_id, resolution, headers=None, note=None):
    """Resolve an INVESTIGATING case at its current version."""
    case = get_success_data(api_client.get_exception_case(case_id, headers or AGENT))
    payload = resolve_exception_payload(resolution, case["version"], note=note)
    return get_success_data(
        api_client.resolve_exception_case(case_id, payload, headers or AGENT2)
    )


def open_and_investigate(order_id, kind, note="opened", return_item_id=None):
    """Open an exception (AGENT) and move it to INVESTIGATING. Returns the
    case snapshot at INVESTIGATING (with its fresh version)."""
    case = open_exception(order_id, kind, note=note, return_item_id=return_item_id)
    return start_investigation(case["id"])


# --- Tier 4: tote helpers ---------------------------------------------------------

def setup_tote_with_route(location, route_overrides=None):
    """PLANNED route from location + FILLING tote at location.
    Returns (route, tote)."""
    route = create_route(location["id"], **(route_overrides or {}))
    tote = create_tote(route["id"], location["id"])
    return route, tote


def add_order_to_tote(tote, order, location_id):
    """Add a DROPPED_OFF order to a FILLING tote at its current version."""
    from .factories import tote_membership_payload
    return get_success_data(
        api_client.add_order_to_tote(
            tote["id"],
            tote_membership_payload(order["id"], tote["version"]),
            make_location_operator_headers(location_id),
        )
    )
