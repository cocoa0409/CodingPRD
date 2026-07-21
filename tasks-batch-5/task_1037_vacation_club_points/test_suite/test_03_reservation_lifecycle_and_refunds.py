"""Confirm/cancel transitions and the cancellation refund ladder.

Queue A: dv_cancellation_refund_partial_on_reservation, bpc_full_refund_days_out_boundary.
Queue B: confirm-twice, cancel-not-found, derived available reconciliation corners.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_member_headers,
    new_member,
    set_clock,
    setup_confirmed_reservation,
    setup_held_reservation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


# ─── dv_cancellation_refund_partial_on_reservation ────────────────────────

def test_partial_cancel_refunds_floor_half(api):
    """PRD §3.5: "If days_out is at least 15 but less than 60, the refund is partial
    and refunded_points equals the floor of half the points_cost, with the forfeited
    remainder staying committed."

    Design: Difficulty/dual_variant_calc/dv_cancellation_refund_partial_on_reservation
    """
    # Clock 2026-07-01, check_in 2026-08-10 -> days_out 40 (PARTIAL). Cost 1000.
    world = setup_held_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=2)
    res = validate_success(api.cancel_reservation(world["reservation"]["id"], world["member_headers"]), 200)
    assert res["status"] == "CANCELLED"
    assert res["refunded_points"] == 500


def test_partial_cancel_releases_only_refunded_points(api):
    """PRD §3.5: "the paying bucket's points_used is reduced by exactly that refunded
    amount (any forfeited remainder remains used)".

    Design: Difficulty/dual_variant_calc/dv_cancellation_refund_partial_on_reservation
    """
    world = setup_held_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=2)
    api.cancel_reservation(world["reservation"]["id"], world["member_headers"])
    bucket = validate_success(api.get_points_bucket(world["bucket"]["id"], ADMIN), 200)
    assert bucket["points_used"] == 500  # 1000 committed, 500 refunded, 500 forfeited stays used
    assert bucket["points_available"] == 4500


# ─── bpc_full_refund_days_out_boundary ────────────────────────────────────

def test_full_refund_at_exactly_60_days_out(api):
    """PRD §3.5: "If days_out is at least 60, the refund is full and refunded_points
    equals the entire points_cost." PRD §3.5: "days_out, the whole number of days
    from the current clock date to check_in."

    Design: Difficulty/boundary_precision_check/bpc_full_refund_days_out_boundary
    """
    # Book at 2026-06-01, then move clock to 2026-06-11 -> days_out to 2026-08-10 is exactly 60.
    world = setup_held_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=1, clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-11T00:00:00Z")
    res = validate_success(api.cancel_reservation(world["reservation"]["id"], world["member_headers"]), 200)
    assert res["refunded_points"] == 1000


def test_full_refund_zeroes_bucket_points_used(api):
    """PRD §3.5: "The computed refunded_points is recorded on the reservation, the
    paying bucket's points_used is reduced by exactly that refunded amount".

    Design: Difficulty/boundary_precision_check/bpc_full_refund_days_out_boundary
    """
    world = setup_held_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=1, clock="2026-06-01T00:00:00Z")
    set_clock("2026-06-11T00:00:00Z")
    api.cancel_reservation(world["reservation"]["id"], world["member_headers"])
    bucket = validate_success(api.get_points_bucket(world["bucket"]["id"], ADMIN), 200)
    assert bucket["points_used"] == 0
    assert bucket["points_available"] == 5000


# ─── Queue B corners ──────────────────────────────────────────────────────

def test_confirm_already_confirmed_rejected(api):
    """PRD §3.5: "Confirmation is legal only from `HELD` — confirming anything else is
    rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/corner_confirm_twice_invalid_state
    """
    world = setup_confirmed_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=1)
    resp = api.confirm_reservation(world["reservation"]["id"], world["member_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_cancel_unknown_reservation_not_found(api):
    """PRD §2.9: "a missing reservation `ERR_RESERVATION_NOT_FOUND`, a missing waitlist
    entry `ERR_WAITLIST_NOT_FOUND`".

    Design: Corner/validations/corner_not_found_reservation_on_cancel
    """
    set_clock("2026-07-01T00:00:00Z")
    member = new_member(owned_points=5000)
    resp = api.cancel_reservation(NON_EXISTENT_UUID, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_FOUND.value, 404)


def test_available_reconciled_after_partial_refund(api):
    """PRD §2.6: "It rises when points are committed and falls when they are released
    (a refund, a revoked certificate, a rejected or completed transfer's escrow
    release). Every one of these counter changes recomputes points_available in the
    same operation."

    Design: Corner/cross_cutting_complexity_layers/corner_derived_reconcile_available_after_partial_refund
    """
    world = setup_held_reservation("2026-08-10", "2026-08-14", owned_points=5000, total_units=1)
    # Book commits 1000 (available 4000); partial cancel (days_out 40) refunds 500.
    api.cancel_reservation(world["reservation"]["id"], world["member_headers"])
    bucket = validate_success(api.get_points_bucket(world["bucket"]["id"], ADMIN), 200)
    assert bucket["points_used"] == 500
    assert bucket["points_available"] == 4500
