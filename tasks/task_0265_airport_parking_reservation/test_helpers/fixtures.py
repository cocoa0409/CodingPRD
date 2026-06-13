"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface as
clear "setup failed" errors rather than confusing assertion failures.

Every helper builds its preconditions from scratch via PRD-declared endpoints — the
runner restarts the server (empty DB) before every test. The FacilityAdmin role drives
clock/seed operations; Customer ownership-gated helpers thread make_customer_headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload, create_vehicle_payload, create_lot_payload,
    create_rate_plan_payload, create_cancellation_policy_payload,
    create_shuttle_trip_payload, create_reservation_payload, assign_shuttle_payload,
    clock_set_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["facility_admin_headers"]
OPERATOR = TEST_USERS["lot_operator_headers"]

_EMAIL_COUNTER = {"n": 0}


def _unique_email(prefix="cust"):
    _EMAIL_COUNTER["n"] += 1
    return f"{prefix}{_EMAIL_COUNTER['n']}@example.com"


# ─── Clock ───────────────────────────────────────────────────────────────────
def set_clock(iso: str):
    """Set the server clock to an absolute instant."""
    return get_success_data(api_client.clock_set(clock_set_payload(iso), ADMIN))


# ─── Primitive creators (return the created entity dict) ─────────────────────
def create_customer(email=None, full_name="Test Customer"):
    res = api_client.create_customer(
        create_customer_payload(email=email or _unique_email(), full_name=full_name), ADMIN)
    return get_success_data(res)


def create_lot(**overrides):
    res = api_client.create_lot(create_lot_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_rate_plan(lot_id, **overrides):
    res = api_client.create_rate_plan(create_rate_plan_payload(lot_id, **overrides), ADMIN)
    return get_success_data(res)


def create_cancellation_policy(lot_id, **overrides):
    res = api_client.create_cancellation_policy(
        create_cancellation_policy_payload(lot_id, **overrides), ADMIN)
    return get_success_data(res)


def create_vehicle(customer_id, **overrides):
    res = api_client.create_vehicle(create_vehicle_payload(customer_id, **overrides), ADMIN)
    return get_success_data(res)


def create_shuttle_trip(lot_id, **overrides):
    res = api_client.create_shuttle_trip(create_shuttle_trip_payload(lot_id, **overrides), ADMIN)
    return get_success_data(res)


def get_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, ADMIN))


def get_reservation(reservation_id):
    return get_success_data(api_client.get_reservation(reservation_id, ADMIN))


def get_shuttle_trip(trip_id):
    return get_success_data(api_client.get_shuttle_trip(trip_id, ADMIN))


def list_payment_txns(reservation_id):
    res = api_client.list_reservation_payment_txns(reservation_id, ADMIN)
    data = get_success_data(res)
    # paginated list endpoints return the array in data
    return data if isinstance(data, list) else data


# ─── Tier 2: Booking-ready scenario ──────────────────────────────────────────
def setup_booking_scenario(clock="2026-06-30T09:00:00Z", lot_overrides=None,
                           rate_plan_overrides=None, vehicle_overrides=None,
                           with_policy=False, policy_overrides=None):
    """Clock + customer + lot + rate plan + vehicle, ready for a POST /reservations.

    Returns a dict with keys: customer, lot, rate_plan, vehicle, policy (or None),
    and lot_version (the lot's current version, freshly fetched).
    """
    set_clock(clock)
    customer = create_customer()
    lot = create_lot(**(lot_overrides or {}))
    rate_plan = create_rate_plan(lot["id"], **(rate_plan_overrides or {}))
    policy = None
    if with_policy:
        policy = create_cancellation_policy(lot["id"], **(policy_overrides or {}))
    vehicle = create_vehicle(customer["id"], **(vehicle_overrides or {}))
    fresh_lot = get_lot(lot["id"])
    return {
        "customer": customer,
        "lot": fresh_lot,
        "rate_plan": rate_plan,
        "vehicle": vehicle,
        "policy": policy,
        "lot_version": fresh_lot["version"],
    }


def book_reservation(scenario, headers=None, **reservation_overrides):
    """Book a reservation against a scenario dict. Uses the current lot version.

    Returns (response, reservation_data_or_None). The reservation data is None when
    the create did not return a 2xx (caller can inspect the response for the error).
    """
    lot = get_lot(scenario["lot"]["id"])
    payload = create_reservation_payload(
        scenario["customer"]["id"], lot["id"], scenario["vehicle"]["id"],
        scenario["rate_plan"]["id"], lot["version"], **reservation_overrides)
    res = api_client.create_reservation(payload, headers or ADMIN)
    data = None
    if 200 <= res.status_code < 300:
        data = res.json()["data"]
    return res, data


def create_booked_reservation(clock="2026-06-30T09:00:00Z", lot_overrides=None,
                              rate_plan_overrides=None, vehicle_overrides=None,
                              with_policy=False, policy_overrides=None,
                              **reservation_overrides):
    """Full path from empty DB to one BOOKED reservation. Returns (scenario, reservation)."""
    scenario = setup_booking_scenario(
        clock=clock, lot_overrides=lot_overrides, rate_plan_overrides=rate_plan_overrides,
        vehicle_overrides=vehicle_overrides, with_policy=with_policy,
        policy_overrides=policy_overrides)
    res, reservation = book_reservation(scenario, **reservation_overrides)
    assert reservation is not None, f"Setup failed booking reservation: {res.status_code} {res.text}"
    return scenario, reservation


# ─── Tier 3: Check-in / check-out lifecycle shortcuts ────────────────────────
def create_checked_in_reservation(scheduled_start="2026-07-01T10:00:00Z",
                                  scheduled_end="2026-07-02T10:00:00Z",
                                  check_in_clock=None, clock="2026-06-30T09:00:00Z",
                                  lot_overrides=None, rate_plan_overrides=None,
                                  vehicle_overrides=None, with_policy=False,
                                  policy_overrides=None, prepaid=False):
    """Book, advance the clock to arrival, and check in. Returns (scenario, reservation)."""
    scenario, reservation = create_booked_reservation(
        clock=clock, lot_overrides=lot_overrides, rate_plan_overrides=rate_plan_overrides,
        vehicle_overrides=vehicle_overrides, with_policy=with_policy,
        policy_overrides=policy_overrides, scheduled_start=scheduled_start,
        scheduled_end=scheduled_end, prepaid=prepaid)
    set_clock(check_in_clock or scheduled_start)
    res = api_client.check_in_reservation(reservation["id"], OPERATOR)
    checked_in = get_success_data(res)
    return scenario, checked_in


def check_out_reservation_at(reservation_id, check_out_clock):
    """Set the clock to check_out_clock then check the reservation out. Returns data."""
    set_clock(check_out_clock)
    res = api_client.check_out_reservation(reservation_id, OPERATOR)
    return get_success_data(res)


# ─── Strike building: drive a customer to SUSPENDED ──────────────────────────
def drive_customer_to_suspended(strike_lot=None, customer=None,
                                base_clock="2026-06-30T09:00:00Z"):
    """Create (or reuse) a customer + a strike lot, then mark three no-shows so the
    customer reaches no_show_strikes==3 and status==SUSPENDED.

    Each no-show: book a BOOKED reservation with scheduled_start just after the clock,
    advance the clock past the 30-min no-show grace with /_clock/set (which does NOT
    sweep), then mark-no-show. Re-fetches the lot version before each booking so the
    OCC expected_lot_version stays fresh.

    Returns (customer, strike_lot).
    """
    if customer is None or strike_lot is None:
        set_clock(base_clock)
    if customer is None:
        customer = create_customer()
    if strike_lot is None:
        strike_lot = create_lot(standard_capacity=3)
    rate_plan = create_rate_plan(strike_lot["id"])
    vehicle = create_vehicle(customer["id"], plate="STRIKE")

    # Three no-show cycles, each: (booking clock strictly before start, start, end,
    # clock past the 30-min no-show grace). /_clock/set never sweeps, so each cycle's
    # mark-no-show is explicit. After each no-show the lot version advances, so the
    # next booking re-fetches it.
    cycles = [
        ("2026-06-30T09:00:00Z", "2026-06-30T09:05:00Z", "2026-07-01T09:30:00Z", "2026-06-30T09:40:00Z"),
        ("2026-06-30T09:40:00Z", "2026-06-30T09:45:00Z", "2026-07-01T09:45:00Z", "2026-06-30T10:20:00Z"),
        ("2026-06-30T10:20:00Z", "2026-06-30T10:25:00Z", "2026-07-01T09:50:00Z", "2026-06-30T11:00:00Z"),
    ]
    for book_clock, start, end, no_show_clock in cycles:
        set_clock(book_clock)
        lot = get_lot(strike_lot["id"])
        payload = create_reservation_payload(
            customer["id"], lot["id"], vehicle["id"], rate_plan["id"], lot["version"],
            scheduled_start=start, scheduled_end=end, prepaid=False)
        res = api_client.create_reservation(payload, ADMIN)
        reservation = get_success_data(res)
        set_clock(no_show_clock)
        api_client.mark_no_show(reservation["id"], ADMIN)

    return customer, strike_lot


# ─── Shuttle assignment ──────────────────────────────────────────────────────
def assign_reservation_to_trip(reservation_id, trip_id):
    """Assign a reservation to a trip using the trip's current version. Returns data."""
    trip = get_shuttle_trip(trip_id)
    res = api_client.assign_shuttle(
        reservation_id, assign_shuttle_payload(trip_id, trip["version"]), ADMIN)
    return get_success_data(res)
