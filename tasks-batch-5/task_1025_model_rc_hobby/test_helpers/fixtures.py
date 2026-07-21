"""Composite setup helpers.

Every test starts against an empty database (the runner restarts the server
before each test), so these helpers build all preconditions from scratch using
only PRD-declared endpoints. They use the lenient get_success_data() validator
so a broken setup surfaces as a clear "Setup failed" rather than a confusing
assertion later.

Most setups act AS StoreStaff, which is an opaque operator permitted to create
members and act on their behalf; ownership threading via make_customer_headers
is only needed when a test acts AS a Customer.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_customer_payload, create_product_payload, create_campaign_payload,
    create_reservation_payload, create_order_payload, order_line,
    create_service_job_payload, create_race_event_payload, create_race_entry_payload,
)
from .constants import OPEN_WINDOW_START, OPEN_WINDOW_END

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]


# =========================================================================
# Primitives
# =========================================================================
def make_customer(api, ack=False, **overrides) -> dict:
    """Create a member. If ack=True, also record the hazmat safety ack."""
    cust = get_success_data(api.create_customer(create_customer_payload(**overrides), STAFF))
    if ack:
        cust = get_success_data(api.safety_ack(cust["id"], STAFF))
    return cust


def make_product(api, **overrides) -> dict:
    return get_success_data(api.create_product(create_product_payload(**overrides), STAFF))


def make_order(api, customer_id, lines, headers=None, **overrides) -> dict:
    """Create a DRAFT order for customer_id with the given line dicts."""
    payload = create_order_payload(customer_id=customer_id, lines=lines, **overrides)
    return get_success_data(api.create_order(payload, headers or STAFF))


def place_order(api, order_id, headers=None) -> dict:
    return get_success_data(api.transition_order(order_id, {"action": "PLACE"}, headers or STAFF))


def pay_order(api, order_id, amount_cents, headers=None) -> dict:
    return get_success_data(api.pay_order(order_id, {"amount_cents": amount_cents}, headers or STAFF))


def fulfill_order(api, order_id, headers=None) -> dict:
    return get_success_data(api.transition_order(order_id, {"action": "FULFILL"}, headers or STAFF))


def cancel_order(api, order_id, headers=None) -> dict:
    return get_success_data(api.transition_order(order_id, {"action": "CANCEL"}, headers or STAFF))


# =========================================================================
# Order composite shortcuts
# =========================================================================
def make_placed_order(api, customer=None, ack=False, product=None,
                      product_type="KIT", price_cents=10000, stock_on_hand=10,
                      quantity=1, unit_price_cents=10000) -> tuple:
    """Create customer + product (unless supplied), a single-line order, and
    PLACE it. Returns (order, customer, product)."""
    if customer is None:
        customer = make_customer(api, ack=ack)
    if product is None:
        product = make_product(api, product_type=product_type,
                               price_cents=price_cents, stock_on_hand=stock_on_hand)
    order = make_order(api, customer["id"],
                       [order_line(product["id"], quantity, unit_price_cents)])
    order = place_order(api, order["id"])
    return order, customer, product


def make_fulfilled_order(api, customer=None, product=None,
                         unit_price_cents=10000, quantity=1, stock_on_hand=10) -> tuple:
    """Create -> place -> pay(total) -> fulfill. Returns (order, customer, product)."""
    order, customer, product = make_placed_order(
        api, customer=customer, product=product,
        price_cents=unit_price_cents, stock_on_hand=stock_on_hand,
        quantity=quantity, unit_price_cents=unit_price_cents)
    pay_order(api, order["id"], order["total_cents"])
    order = fulfill_order(api, order["id"])
    return order, customer, product


# =========================================================================
# Campaign / reservation composites
# =========================================================================
def campaign_version(api, campaign_id) -> int:
    return get_success_data(api.get_campaign(campaign_id, STAFF))["version"]


def make_open_campaign(api, total_allocation_units=10, unit_price_cents=10000,
                       product=None, product_stock=50, product_type="RC_VEHICLE",
                       reservation_open_at=OPEN_WINDOW_START,
                       reservation_close_at=OPEN_WINDOW_END) -> tuple:
    """Create a product + campaign and OPEN it. Returns (campaign, product)."""
    if product is None:
        product = make_product(api, product_type=product_type,
                               price_cents=unit_price_cents, stock_on_hand=product_stock)
    camp = get_success_data(api.create_campaign(create_campaign_payload(
        product_id=product["id"], total_allocation_units=total_allocation_units,
        unit_price_cents=unit_price_cents, reservation_open_at=reservation_open_at,
        reservation_close_at=reservation_close_at), STAFF))
    camp = get_success_data(api.open_campaign(camp["id"], STAFF))
    return camp, product


def add_reservation(api, campaign_id, customer_id, requested_units, headers=None) -> dict:
    """Read the campaign's current version, then create a HELD reservation.
    Auto-threading the version keeps sequential reservations off the OCC path."""
    ver = campaign_version(api, campaign_id)
    return get_success_data(api.create_reservation(
        campaign_id,
        create_reservation_payload(customer_id=customer_id,
                                   requested_units=requested_units,
                                   expected_campaign_version=ver),
        headers or STAFF))


def allocate_campaign(api, campaign_id) -> dict:
    return get_success_data(api.allocate_campaign(campaign_id, STAFF))


def make_allocated_reservation(api, requested_units=5, total_allocation_units=10,
                               unit_price_cents=10000, product_stock=50,
                               customer=None) -> dict:
    """Full chain: product + OPEN campaign + one reservation + allocate.
    Returns dict with keys: campaign, product, reservation, customer."""
    if customer is None:
        customer = make_customer(api)
    camp, product = make_open_campaign(
        api, total_allocation_units=total_allocation_units,
        unit_price_cents=unit_price_cents, product_stock=product_stock)
    res = add_reservation(api, camp["id"], customer["id"], requested_units)
    camp = allocate_campaign(api, camp["id"])
    res = get_success_data(api.get_reservation(res["id"], STAFF))
    return {"campaign": camp, "product": product, "reservation": res, "customer": customer}


def make_converted_reservation(api, requested_units=5, total_allocation_units=10,
                               unit_price_cents=10000, product_stock=100,
                               customer=None) -> dict:
    """Chain through CONVERT: the reservation becomes CONVERTED and its linked
    order is created (already PLACED). Returns dict with campaign, product,
    reservation, customer, order."""
    ctx = make_allocated_reservation(
        api, requested_units=requested_units,
        total_allocation_units=total_allocation_units,
        unit_price_cents=unit_price_cents, product_stock=product_stock,
        customer=customer)
    res = get_success_data(api.transition_reservation(
        ctx["reservation"]["id"], {"action": "CONVERT"}, STAFF))
    ctx["reservation"] = res
    ctx["order"] = get_success_data(api.get_order(res["order_id"], STAFF))
    return ctx


# =========================================================================
# Service job composites
# =========================================================================
def make_service_job(api, customer=None, job_type="REPAIR", **overrides) -> dict:
    if customer is None:
        customer = make_customer(api)
    payload = create_service_job_payload(customer_id=customer["id"], job_type=job_type, **overrides)
    return get_success_data(api.create_service_job(payload, STAFF))


def schedule_job(api, job_id, bench_code, slot_start, slot_end) -> dict:
    return get_success_data(api.transition_service_job(job_id, {
        "action": "SCHEDULE", "bench_code": bench_code,
        "slot_start": slot_start, "slot_end": slot_end}, STAFF))


def _job_action(api, job_id, action, **fields) -> dict:
    payload = {"action": action}
    payload.update(fields)
    return get_success_data(api.transition_service_job(job_id, payload, STAFF))


def make_started_job(api, job_type="REPAIR", estimated_labor_hours=1,
                     estimated_parts_cents=0, bench_code="B1",
                     slot_start="2026-07-02T09:00:00Z",
                     slot_end="2026-07-02T10:00:00Z") -> dict:
    """Create -> DIAGNOSE -> SCHEDULE -> START. Returns the IN_PROGRESS job."""
    job = make_service_job(api, job_type=job_type)
    _job_action(api, job["id"], "DIAGNOSE",
                estimated_labor_hours=estimated_labor_hours,
                estimated_parts_cents=estimated_parts_cents)
    schedule_job(api, job["id"], bench_code, slot_start, slot_end)
    return _job_action(api, job["id"], "START")


# =========================================================================
# Race event / entry composites
# =========================================================================
def make_open_event(api, capacity=8, lane_count=4, entry_fee_cents=1000,
                    event_date="2026-07-15T10:00:00Z",
                    registration_open_at="2026-07-01T00:00:00Z",
                    registration_close_at="2026-07-20T00:00:00Z",
                    name="Test Race") -> dict:
    """Create an event and OPEN it (SCHEDULED -> OPEN)."""
    ev = get_success_data(api.create_race_event(create_race_event_payload(
        capacity=capacity, lane_count=lane_count, entry_fee_cents=entry_fee_cents,
        event_date=event_date, registration_open_at=registration_open_at,
        registration_close_at=registration_close_at, name=name), STAFF))
    return get_success_data(api.transition_race_event(ev["id"], {"action": "OPEN"}, STAFF))


def make_running_event(api, **overrides) -> dict:
    """Create -> OPEN -> RUN (so check-ins are accepted)."""
    ev = make_open_event(api, **overrides)
    return get_success_data(api.transition_race_event(ev["id"], {"action": "RUN"}, STAFF))


def register_entry(api, event_id, customer_id, race_class="STOCK", lane_no=1,
                   heat_start="2026-07-15T10:00:00Z",
                   heat_end="2026-07-15T10:10:00Z", headers=None) -> dict:
    return get_success_data(api.create_race_entry(event_id, create_race_entry_payload(
        customer_id=customer_id, race_class=race_class, lane_no=lane_no,
        heat_start=heat_start, heat_end=heat_end), headers or STAFF))


def set_clock(api, to_iso8601) -> None:
    get_success_data(api.set_clock(to_iso8601, STAFF))
