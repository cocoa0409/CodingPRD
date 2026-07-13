"""Escort confirmation: half-open pilot-car double-booking (with back-to-back
adjacency allowed) and the pilot-availability precondition.
"""
from test_helpers import (
    TEST_USERS, make_carrier_headers,
    validate_success, validate_error,
    ApiErrorId,
    new_carrier, new_pilot_car, new_permit, add_escort, confirm_escort,
)

OFFICER = TEST_USERS["permit_officer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / pilot_car_halfopen_double_booking
# ---------------------------------------------------------------------------
def _three_escorts_one_pilot(api):
    carrier = new_carrier(api)
    pilot = new_pilot_car(api)
    permit = new_permit(api, carrier["id"])
    e1 = add_escort(api, permit["id"], carrier["id"], pilot["id"], role="FRONT",
                    window_start_utc="2026-06-05T10:00:00Z", window_end_utc="2026-06-05T12:00:00Z")
    e2 = add_escort(api, permit["id"], carrier["id"], pilot["id"], role="REAR",
                    window_start_utc="2026-06-05T11:00:00Z", window_end_utc="2026-06-05T13:00:00Z")
    e3 = add_escort(api, permit["id"], carrier["id"], pilot["id"], role="POLICE",
                    window_start_utc="2026-06-05T12:00:00Z", window_end_utc="2026-06-05T13:00:00Z")
    confirm_escort(api, e1["id"], carrier["id"])
    return carrier, e2["id"], e3["id"]


def test_overlapping_escort_double_booked(api):
    """PRD §3.5: "no other `CONFIRMED` assignment for the same `pilot_car_id` may
    overlap the half-open window from `window_start_utc` up to but not including
    `window_end_utc`, or the request is rejected with `ERR_PILOT_CAR_DOUBLE_BOOKED`".

    Design: Difficulty/resource_temporal_overlap/pilot_car_halfopen_double_booking
    """
    carrier, e2_id, _e3_id = _three_escorts_one_pilot(api)
    resp = api.confirm_escort(e2_id, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_PILOT_CAR_DOUBLE_BOOKED)


def test_back_to_back_escort_allowed(api):
    """PRD §3.5: "because the interval is half-open, two back-to-back windows that
    merely touch at an endpoint do not conflict."

    Design: Difficulty/resource_temporal_overlap/pilot_car_halfopen_double_booking
    """
    carrier, _e2_id, e3_id = _three_escorts_one_pilot(api)
    confirmed = validate_success(api.confirm_escort(e3_id, make_carrier_headers(carrier["id"])), 200)
    assert confirmed["status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / confirm_requires_pilot_available
# ---------------------------------------------------------------------------
def _pending_escort_on_unavailable_pilot(api):
    carrier = new_carrier(api)
    pilot = new_pilot_car(api, status="OUT_OF_SERVICE")
    permit = new_permit(api, carrier["id"])
    escort = add_escort(api, permit["id"], carrier["id"], pilot["id"], role="FRONT",
                        window_start_utc="2026-06-05T10:00:00Z", window_end_utc="2026-06-05T12:00:00Z")
    return carrier, escort["id"]


def test_confirm_unavailable_pilot_rejected(api):
    """PRD §3.5: "the referenced pilot car's `status` must be `AVAILABLE`, or the
    request is rejected with `ERR_PILOT_CAR_UNAVAILABLE`".

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_pilot_available
    """
    carrier, escort_id = _pending_escort_on_unavailable_pilot(api)
    resp = api.confirm_escort(escort_id, make_carrier_headers(carrier["id"]))
    validate_error(resp, ApiErrorId.ERR_PILOT_CAR_UNAVAILABLE)


def test_confirm_unavailable_pilot_leaves_pending(api):
    """PRD §3.5: "the referenced pilot car's `status` must be `AVAILABLE`, or the
    request is rejected with `ERR_PILOT_CAR_UNAVAILABLE`".

    The rejected confirmation must leave the assignment in PENDING.

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_pilot_available
    """
    carrier, escort_id = _pending_escort_on_unavailable_pilot(api)
    api.confirm_escort(escort_id, make_carrier_headers(carrier["id"]))
    escort = validate_success(api.get_escort_assignment(escort_id, OFFICER), 200)
    assert escort["status"] == "PENDING"
