"""Ticket activation/validation lifecycle, precedence, and monthly-pass overlap."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_passenger_headers,
)
from test_helpers import fixtures as fx


# ==========================================================================
# priority_pair_validation_conflict / activate_state_beats_temporal
# ==========================================================================

def test_activate_already_activated_past_deadline_reports_state_error(api):
    """PRD 2.7: "the target resource's state eligibility for the requested transition, then
    (6) business-referential rules such as reduced-fare eligibility and inspection/ticket
    linkage, then (7) time-window rules such as activation deadlines and refund windows"
    PRD 3.4: "Attempting to activate a ticket that is not in `PURCHASED` fails with
    `ERR_INVALID_TICKET_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_temporal
    """
    fx.set_clock(api)  # 2026-03-01
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    fx.activate_ticket(api, tkt["id"], pax["id"])  # now ACTIVATED
    fx.set_clock(api, "2026-07-01T00:00:00Z")  # > 90 days past purchase
    resp = api.activate_ticket(tkt["id"], make_passenger_headers(pax["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_TICKET_STATE.value)


def test_activate_purchased_past_deadline_reports_temporal_error(api):
    """PRD 3.4: "From `PURCHASED` a rider may activate the ticket, provided the current
    clock is no later than 90 days after the ticket's creation; activating after that window
    closes fails with `ERR_TICKET_ACTIVATION_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/activate_state_beats_temporal
    """
    fx.set_clock(api)  # 2026-03-01
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")  # stays PURCHASED
    fx.set_clock(api, "2026-07-01T00:00:00Z")  # > 90 days past purchase
    resp = api.activate_ticket(tkt["id"], make_passenger_headers(pax["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_ACTIVATION_EXPIRED.value)


# ==========================================================================
# resource_temporal_overlap / monthly_pass_same_month_overlap_rejected
# ==========================================================================

def test_monthly_pass_same_month_overlap_rejected(api):
    """PRD 3.4: "For a monthly pass, activation is additionally blocked when the passenger
    already holds another activated monthly ticket for the same origin-destination zone pair
    whose validity month overlaps the one being activated, in which case the request fails
    with `ERR_PASS_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/monthly_pass_same_month_overlap_rejected
    """
    fx.set_clock(api)  # 2026-03-01
    fp = fx.create_fare_product(api, ticket_type="MONTHLY", base_fare_cents=20000,
                                peak_surcharge_cents=0)
    pax = fx.create_passenger(api)
    tkt1 = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK")
    tkt2 = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK")
    fx.activate_ticket(api, tkt1["id"], pax["id"])  # validity March
    resp = api.activate_ticket(tkt2["id"], make_passenger_headers(pax["id"]))
    validate_error(resp, ApiErrorId.ERR_PASS_PERIOD_OVERLAP.value)
    assert fx.get_ticket(api, tkt2["id"])["status"] == "PURCHASED"


def test_monthly_pass_adjacent_month_allowed(api):
    """PRD 3.4: "activation is additionally blocked when the passenger already holds another
    activated monthly ticket for the same origin-destination zone pair whose validity month
    overlaps the one being activated, in which case the request fails with
    `ERR_PASS_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/monthly_pass_same_month_overlap_rejected
    """
    fx.set_clock(api)  # 2026-03-01
    fp = fx.create_fare_product(api, ticket_type="MONTHLY", base_fare_cents=20000,
                                peak_surcharge_cents=0)
    pax = fx.create_passenger(api)
    tkt1 = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK")
    tkt2 = fx.purchase_ticket(api, pax["id"], fp["id"], "OFF_PEAK")
    fx.activate_ticket(api, tkt1["id"], pax["id"])  # validity March
    fx.set_clock(api, "2026-04-01T00:00:00Z")  # activate second for April validity
    data = validate_success(api.activate_ticket(tkt2["id"], make_passenger_headers(pax["id"])), 200)
    assert data["status"] == "ACTIVATED"


# ==========================================================================
# Corner: validation state / expiry
# ==========================================================================

def test_validate_purchased_ticket_returns_invalid_state(api):
    """PRD 3.4: "Scan validation consumes a single-journey ticket. It is permitted only
    from `ACTIVATED`, only for a `SINGLE` ticket"
    PRD 3.4: "a validation on a ticket in the wrong state fails with
    `ERR_INVALID_TICKET_STATE`."

    Design: Corner/state_machines/validate_purchased_ticket_returns_invalid_state
    """
    fx.set_clock(api)
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")  # never activated
    resp = api.validate_ticket(tkt["id"], make_passenger_headers(pax["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_TICKET_STATE.value)


def test_validate_after_expiry_returns_ticket_expired(api):
    """PRD 3.4: "only while the current clock is at or before the ticket's `expires_at`; a
    validation attempted after expiry fails with `ERR_TICKET_EXPIRED`"

    Design: Corner/validations/validate_after_expiry_returns_ticket_expired
    """
    fx.set_clock(api)  # 2026-03-01T00:00
    fp = fx.create_fare_product(api)
    pax = fx.create_passenger(api)
    tkt = fx.purchase_ticket(api, pax["id"], fp["id"], "PEAK")
    fx.activate_ticket(api, tkt["id"], pax["id"])  # expires 01:30
    fx.set_clock(api, "2026-03-01T02:00:00Z")
    resp = api.validate_ticket(tkt["id"], make_passenger_headers(pax["id"]))
    validate_error(resp, ApiErrorId.ERR_TICKET_EXPIRED.value)
