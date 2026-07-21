"""Departure-guarantee preconditions and supplier-booking confirm gating (corner)."""
from test_helpers import (
    validate_error, OPERATOR,
    ApiErrorId,
    setup_open_departure, enroll, make_supplier, make_supplier_booking,
)


def test_guarantee_below_min_returns_guarantee_not_met(api):
    """PRD §3.2: "First, active_enrollment_count must be at least min_to_guarantee; if it
    is below that threshold the request is rejected with ERR_GUARANTEE_NOT_MET."

    Design: Corner/state_machines/guarantee_below_min_returns_guarantee_not_met
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", min_to_guarantee=10)
    enroll(api, ctx["departure"]["id"], traveler_name="Solo S")  # only 1 < 10
    resp = api.guarantee_departure(ctx["departure"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_MET.value, expected_status=409)


def test_guarantee_with_no_chaperones_returns_not_enough_chaperones(api):
    """PRD §3.2: "the number of confirmed chaperones on the departure must be at least the
    enrollment count divided by the chaperone ratio and rounded up to the next whole number
    — that is, at least the ceiling of active_enrollment_count divided by chaperone_ratio;
    if there are too few, the request is rejected with ERR_NOT_ENOUGH_CHAPERONES."

    Design: Corner/state_machines/guarantee_with_no_chaperones_returns_not_enough_chaperones
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", min_to_guarantee=2, chaperone_ratio=6)
    enroll(api, ctx["departure"]["id"], traveler_name="G1")
    enroll(api, ctx["departure"]["id"], traveler_name="G2", traveler_dob="2010-05-02T00:00:00Z")
    # active_enrollment_count 2 >= min 2, but ceil(2/6)=1 required and ZERO chaperones exist.
    resp = api.guarantee_departure(ctx["departure"]["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_NOT_ENOUGH_CHAPERONES.value, expected_status=409)


def test_supplier_booking_confirm_requires_departure_guaranteed(api):
    """PRD §3.9: "Confirming a booking advances it HELD → CONFIRMED and is permitted only
    when the parent departure's status is GUARANTEED; otherwise it is rejected with
    ERR_INVALID_STATE."

    Design: Corner/state_machines/supplier_booking_confirm_requires_departure_guaranteed
    """
    ctx = setup_open_departure(api, clock="2026-07-15T00:00:00Z")  # departure only OPEN, not GUARANTEED
    sup = make_supplier(api, name="Hotel Roma")
    booking = make_supplier_booking(
        api, ctx["departure"]["id"], sup["id"],
        "2026-11-01T00:00:00Z", "2026-11-04T00:00:00Z", room_block=10, cost_cents=500000,
    )
    resp = api.confirm_supplier_booking(booking["id"], OPERATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
