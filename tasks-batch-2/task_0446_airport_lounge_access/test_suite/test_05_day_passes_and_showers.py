"""Day-pass redemption gates, shower booking with the turnover buffer, the
allotment-year reset, and lounge reopen / day-pass expiry.

Day passes redeem only against their own lounge (PRD §3.6). Shower bookings honour
a half-open interval with a per-suite turnover buffer (PRD §3.7). Roll-year
advances the allotment baseline (PRD §3.9). Covers queue-A resource_temporal_overlap
(shower) and queue-B validation / calculation / endpoint corners.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    api_client,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    make_lounge_agent_headers,
    fixtures,
)

ADMIN = TEST_USERS["network_admin_headers"]


# ─── Queue A: resource_temporal_overlap — shower buffered turnover ───────────
def test_shower_booking_blocked_at_buffered_boundary(api):
    """PRD §3.7: "A proposed booking conflicts with an existing `BOOKED` reservation
    of the same suite exactly when the proposed `start_at` falls before that
    existing reservation's `end_at` plus the turnover minutes, and the existing
    reservation's `start_at` falls before the proposed `end_at`; any such conflict
    rejects the new booking with `ERR_SHOWER_CONFLICT` (HTTP 409)."

    Existing [10:00,10:30) with turnover 15 -> buffered end 10:45; a booking at
    10:30 conflicts (10:30 < 10:45).

    Design: Difficulty/resource_temporal_overlap/rto_shower_interval_buffered_turnover
    """
    lounge, member, visit, suite = fixtures.setup_shower_ready_visit(
        suite_overrides={"turnover_minutes": 15}
    )
    fixtures.book_shower(
        suite["id"], visit["id"], member["id"],
        "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z",
    )
    resp = api_client.create_shower_reservation(
        {"shower_suite_id": suite["id"], "visit_id": visit["id"],
         "start_at": "2026-06-01T10:30:00Z", "end_at": "2026-06-01T11:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SHOWER_CONFLICT.value)


def test_shower_booking_allowed_exactly_at_buffer_boundary(api):
    """PRD §3.7: "when the turnover is greater than zero, a booking starting exactly
    at the existing reservation's `end_at` is rejected and must instead start at or
    after that end plus the turnover minutes."

    Existing [10:00,10:30) with turnover 15 -> a booking starting 10:45 is allowed
    (10:45 is not before buffered end 10:45).

    Design: Difficulty/resource_temporal_overlap/rto_shower_interval_buffered_turnover
    """
    lounge, member, visit, suite = fixtures.setup_shower_ready_visit(
        suite_overrides={"turnover_minutes": 15}
    )
    fixtures.book_shower(
        suite["id"], visit["id"], member["id"],
        "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z",
    )
    resp = api_client.create_shower_reservation(
        {"shower_suite_id": suite["id"], "visit_id": visit["id"],
         "start_at": "2026-06-01T10:45:00Z", "end_at": "2026-06-01T11:15:00Z"},
        make_member_headers(member["id"]),
    )
    reservation = validate_success(resp, expected_status=201)
    assert reservation["status"] == "BOOKED", reservation


# ─── Queue B: validation / state-machine corners ─────────────────────────────
def test_shower_booking_against_held_visit_rejected(api):
    """PRD §3.7: "The booking is permitted only when the referenced visit is
    `CHECKED_IN` and the suite is not out of service; a booking against a visit that
    is not checked in, or a suite whose `out_of_service` is true, is rejected with
    `ERR_SHOWER_UNAVAILABLE` (HTTP 409)."

    Design: Corner/validations/val_shower_unavailable_visit_not_checked_in
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    lounge = fixtures.create_lounge(airport_code="PDX", capacity=10)
    suite = fixtures.create_shower_suite(lounge["id"], turnover_minutes=0)
    member = fixtures.create_member(plan["id"])
    fixtures.create_card(member["id"])
    visit = fixtures.open_hold(lounge["id"], member_id=member["id"])  # HELD, not checked in

    resp = api_client.create_shower_reservation(
        {"shower_suite_id": suite["id"], "visit_id": visit["id"],
         "start_at": "2026-06-01T10:00:00Z", "end_at": "2026-06-01T10:30:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SHOWER_UNAVAILABLE.value)


def test_complete_cancelled_shower_reservation_rejected(api):
    """PRD §3.7: "A lounge agent staffing the reservation's lounge may instead mark
    a `BOOKED` reservation `COMPLETED`. Both transitions are defined only from
    `BOOKED`."

    A CANCELLED reservation cannot be completed.

    Design: Corner/state_machines/sm_shower_complete_already_cancelled_invalid_state
    """
    lounge, member, visit, suite = fixtures.setup_shower_ready_visit(
        suite_overrides={"turnover_minutes": 0}
    )
    reservation = fixtures.book_shower(
        suite["id"], visit["id"], member["id"],
        "2026-06-01T10:00:00Z", "2026-06-01T10:30:00Z",
    )
    get_success_data(
        api_client.cancel_shower_reservation(reservation["id"], make_member_headers(member["id"]))
    )
    resp = api_client.complete_shower_reservation(
        reservation["id"], make_lounge_agent_headers(lounge["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_day_pass_redemption_on_wrong_lounge_rejected(api):
    """PRD §3.6: "Redemption happens through a visit: a hold opened with a
    `day_pass_id` and then checked in finalises the pass to `REDEEMED` with its
    `redeemed_visit_id` set to that visit, provided the pass was `ISSUED`, not past
    its `valid_until`, and belongs to the visit's lounge."

    A pass bought for LA, redeemed in a hold on LB, is rejected ERR_DAY_PASS_INVALID.

    Design: Corner/validations/val_daypass_invalid_wrong_lounge
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0)
    la = fixtures.create_lounge(airport_code="RDU", capacity=10, day_pass_price_cents=4000)
    lb = fixtures.create_lounge(airport_code="TPA", capacity=10, day_pass_price_cents=4000)
    member = fixtures.create_member(plan["id"])
    day_pass = fixtures.purchase_day_pass_for_member(la["id"], member["id"])

    lb_v = fixtures.get_lounge(lb["id"])["version"]
    resp = api_client.create_visit(
        {"member_id": member["id"], "lounge_id": lb["id"], "day_pass_id": day_pass["id"],
         "guest_count": 0, "expected_lounge_version": lb_v},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DAY_PASS_INVALID.value)


# ─── Queue B: calculation / endpoint corners ─────────────────────────────────
def test_roll_year_resets_visits_used(api):
    """PRD §3.9: "Rolling the year is the reset mechanism. When the operator
    advances a member's allotment year, `membership_year_start` is set to the
    current logical-clock instant, and the usage counters are recomputed; because
    the counters only include visits whose `held_at` is at or after the new year
    start, every prior-year visit drops out and `visits_used` falls back toward
    zero, restoring the member's free allotment for the new year."

    Design: Corner/calculations/calc_roll_year_resets_usage
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="PRESTIGE", included_visits_per_year=10)
    lounge = fixtures.create_lounge(airport_code="DFW", capacity=10)
    member = fixtures.create_member(plan["id"])
    fixtures.create_card(member["id"], valid_until="2028-01-01T00:00:00Z")
    visit = fixtures.open_hold(lounge["id"], member_id=member["id"])
    fixtures.check_in(visit["id"], lounge["id"])
    fixtures.complete_visit(visit["id"], lounge["id"])
    assert fixtures.get_member(member["id"])["visits_used"] == 1

    fixtures.set_clock("2027-06-01T00:00:00Z")
    rolled = get_success_data(api_client.roll_year(member["id"], ADMIN))
    assert rolled["visits_used"] == 0, rolled


def test_reopen_empty_closed_lounge_recomputes_open(api):
    """PRD §3.1: "Reopening a lounge is only defined from `CLOSED`; on reopen the
    system does not blindly return the lounge to `OPEN` but recomputes its status
    from the current occupancy line — landing on `OPEN` if seats remain or on
    `OVERFLOW` if the occupancy line is already at or above capacity (see §3.3)."

    Design: Corner/endpoints/ep_reopen_recomputes_status
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    lounge = fixtures.create_lounge(airport_code="IAH", capacity=10)
    fixtures.close_lounge(lounge["id"], expected_version=lounge["version"])
    reopened = get_success_data(api_client.reopen_lounge(lounge["id"], ADMIN))
    assert reopened["status"] == "OPEN", reopened


def test_sweep_expires_unredeemed_day_pass(api):
    """PRD §3.6: "An `ISSUED` pass that reaches its `valid_until` without being
    redeemed is forfeited: the housekeeping sweep moves it to the terminal
    `EXPIRED` status with no refund."
    PRD §3.8: "Third, the sweep expires day passes: any `ISSUED` pass whose
    `valid_until` is at or before the logical clock moves to `EXPIRED` with no
    refund."

    Design: Corner/endpoints/ep_sweep_expires_day_pass
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    plan = fixtures.create_plan(tier="STANDARD", included_visits_per_year=0, included_guest_visits_per_year=0)
    lounge = fixtures.create_lounge(airport_code="SMF", capacity=10, day_pass_price_cents=4000)
    member = fixtures.create_member(plan["id"])
    day_pass = fixtures.purchase_day_pass_for_member(lounge["id"], member["id"])

    fixtures.set_clock("2026-06-02T01:00:00Z")  # past valid_until (+24h)
    result = get_success_data(api_client.sweep_lounge(lounge["id"], ADMIN))
    assert result["expired_day_pass_count"] == 1, result
    assert get_success_data(api_client.get_day_pass(day_pass["id"], ADMIN))["status"] == "EXPIRED"
