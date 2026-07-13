"""Booking validation layers: referential, temporal, uniqueness, and fiscal.

Covers the layered-precedence conflicts, the court/pro interval rules, the
court-availability dependency, and the standalone temporal validations.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_booking_scenario, setup_member_with_subscription, make_court, make_pro,
    make_reservation, make_stringing_job, make_lesson, set_clock,
    create_reservation_payload, TEST_USERS,
)

FD = TEST_USERS["frontdesk_headers"]


# ─── priority_pair / conflict_referential_court_beats_fiscal_balance ──
def test_court_unavailable_masks_fiscal_balance_error():
    """PRD §2.8: "Lower-numbered layers are evaluated first, and the first layer that
    fails determines the response — a failure at an earlier layer masks any condition
    a later layer would have raised."
    PRD §2.8: "Cross-entity referential state — booking requires the court to be
    AVAILABLE and the booking member to be ACTIVE ... Failures raise
    ERR_COURT_NOT_AVAILABLE, ERR_MEMBER_SUSPENDED, or ERR_SUBSCRIPTION_NOT_ACTIVE as
    appropriate (all 409)."

    Design: Difficulty/priority_pair_validation_conflict/conflict_referential_court_beats_fiscal_balance
    """
    s = setup_booking_scenario()
    make_stringing_job(s["member"]["id"], price_cents=25000)
    get_success_data(api_client.court_maintenance(s["court"]["id"], FD))
    res = api_client.create_reservation(
        create_reservation_payload(s["court"]["id"], s["member"]["id"],
                                   "2026-05-07T10:00:00Z", "2026-05-07T11:00:00Z"), FD)
    validate_error(res, "ERR_COURT_NOT_AVAILABLE")


def test_fiscal_ceiling_condition_present_but_not_reported():
    """PRD §2.8: "Fiscal ceiling — the member's outstanding balance is within the
    allowed maximum; otherwise ERR_BALANCE_LIMIT_EXCEEDED (402). Applies to booking a
    reservation."
    PRD §3.3: "the member's account_balance_cents must not exceed 20000 cents (200
    dollars) at the moment of booking; a balance above that ceiling refuses the booking
    with ERR_BALANCE_LIMIT_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/conflict_referential_court_beats_fiscal_balance
    """
    s = setup_booking_scenario()
    make_stringing_job(s["member"]["id"], price_cents=25000)
    member = validate_success(api_client.get_member(s["member"]["id"], FD), 200)
    assert member["account_balance_cents"] == 25000  # above the 20000 ceiling
    get_success_data(api_client.court_maintenance(s["court"]["id"], FD))
    res = api_client.create_reservation(
        create_reservation_payload(s["court"]["id"], s["member"]["id"],
                                   "2026-05-07T10:00:00Z", "2026-05-07T11:00:00Z"), FD)
    err = validate_error(res, "ERR_COURT_NOT_AVAILABLE")
    assert err["error_id"] != "ERR_BALANCE_LIMIT_EXCEEDED"


# ─── priority_pair / conflict_temporal_overlap_beats_duplicate ────────
def test_identical_slot_rebook_reports_time_conflict():
    """PRD §2.8: "Temporal interval — the booking or lesson interval satisfies the
    future, advance-window, overlap, buffer, and clock-window rules; failures raise
    ERR_BOOKING_IN_PAST, ERR_BOOKING_WINDOW_EXCEEDED, ERR_COURT_TIME_CONFLICT, ..."
    PRD §3.3: "The interval must not half-open-overlap any other non-terminal
    reservation on the same court, else ERR_COURT_TIME_CONFLICT."

    Design: Difficulty/priority_pair_validation_conflict/conflict_temporal_overlap_beats_duplicate_constraint
    """
    s = setup_booking_scenario()
    make_reservation(s["court"]["id"], s["member"]["id"],
                     "2026-05-07T10:00:00Z", "2026-05-07T11:00:00Z")
    res = api_client.create_reservation(
        create_reservation_payload(s["court"]["id"], s["member"]["id"],
                                   "2026-05-07T10:00:00Z", "2026-05-07T11:00:00Z"), FD)
    validate_error(res, "ERR_COURT_TIME_CONFLICT")


def test_time_conflict_masks_duplicate_reservation_error():
    """PRD §2.8: "a failure at an earlier layer masks any condition a later layer would
    have raised."
    PRD §2.8: "Uniqueness and configuration — no duplicate reservation, enrollment, or
    participant ... failures raise ERR_DUPLICATE_RESERVATION, ..."

    Design: Difficulty/priority_pair_validation_conflict/conflict_temporal_overlap_beats_duplicate_constraint
    """
    s = setup_booking_scenario()
    make_reservation(s["court"]["id"], s["member"]["id"],
                     "2026-05-07T10:00:00Z", "2026-05-07T11:00:00Z")
    res = api_client.create_reservation(
        create_reservation_payload(s["court"]["id"], s["member"]["id"],
                                   "2026-05-07T10:00:00Z", "2026-05-07T11:00:00Z"), FD)
    err = validate_error(res, "ERR_COURT_TIME_CONFLICT")
    assert err["error_id"] != "ERR_DUPLICATE_RESERVATION"


# ─── resource_temporal_overlap / court half-open adjacency ────────────
def test_adjacent_court_booking_allowed():
    """PRD §3.3: "the interval is half-open, covering the start and excluding the end."
    PRD §3.3: "The interval must not half-open-overlap any other non-terminal
    reservation on the same court, else ERR_COURT_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/overlap_court_halfopen_adjacency_allowed
    """
    s = setup_booking_scenario()
    make_reservation(s["court"]["id"], s["member"]["id"],
                     "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z")
    r2 = make_reservation(s["court"]["id"], s["member"]["id"],
                          "2026-05-10T11:00:00Z", "2026-05-10T12:00:00Z")
    assert r2["status"] == "BOOKED"


def test_overlapping_court_booking_rejected():
    """PRD §3.3: "The interval must not half-open-overlap any other non-terminal
    reservation on the same court, else ERR_COURT_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/overlap_court_halfopen_adjacency_allowed
    """
    s = setup_booking_scenario()
    make_reservation(s["court"]["id"], s["member"]["id"],
                     "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z")
    res = api_client.create_reservation(
        create_reservation_payload(s["court"]["id"], s["member"]["id"],
                                   "2026-05-10T10:30:00Z", "2026-05-10T11:30:00Z"), FD)
    validate_error(res, "ERR_COURT_TIME_CONFLICT")


# ─── resource_temporal_overlap / pro buffer gap ───────────────────────
def test_pro_zero_gap_lesson_rejected():
    """PRD §3.5: "the assigned pro must have a clear schedule — the lesson interval must
    be separated from the pro's other non-cancelled lessons by at least a 15-minute
    buffer and must not overlap them, else ERR_PRO_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/overlap_pro_buffer_gap_enforced
    """
    pro = make_pro()
    court1 = make_court(name="Indoor 1")
    court2 = make_court(name="Indoor 2")
    make_lesson(pro["id"], court1["id"], "PRIVATE",
                "2026-05-11T10:00:00Z", "2026-05-11T11:00:00Z", 5000, capacity=1)
    from test_helpers import create_lesson_payload
    res = api_client.create_lesson(
        create_lesson_payload(pro["id"], court2["id"], "PRIVATE",
                              "2026-05-11T11:00:00Z", "2026-05-11T11:30:00Z", 5000, capacity=1), FD)
    validate_error(res, "ERR_PRO_TIME_CONFLICT")


def test_pro_15min_gap_lesson_allowed():
    """PRD §3.5: "the assigned pro must have a clear schedule — the lesson interval must
    be separated from the pro's other non-cancelled lessons by at least a 15-minute
    buffer and must not overlap them, else ERR_PRO_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/overlap_pro_buffer_gap_enforced
    """
    pro = make_pro()
    court1 = make_court(name="Indoor 1")
    court2 = make_court(name="Indoor 2")
    make_lesson(pro["id"], court1["id"], "PRIVATE",
                "2026-05-11T10:00:00Z", "2026-05-11T11:00:00Z", 5000, capacity=1)
    l3 = make_lesson(pro["id"], court2["id"], "PRIVATE",
                     "2026-05-11T11:15:00Z", "2026-05-11T12:00:00Z", 5000, capacity=1)
    assert l3["status"] == "SCHEDULED"


# ─── cross_entity_state_dependency / reservation requires court AVAILABLE
def test_booking_on_maintenance_court_rejected():
    """PRD §3.3: "The court must be `AVAILABLE`, else `ERR_COURT_NOT_AVAILABLE`".

    Design: Difficulty/cross_entity_state_dependency/xdep_reservation_requires_court_available
    """
    s = setup_booking_scenario()
    get_success_data(api_client.court_maintenance(s["court"]["id"], FD))
    res = api_client.create_reservation(
        create_reservation_payload(s["court"]["id"], s["member"]["id"],
                                   "2026-05-09T10:00:00Z", "2026-05-09T11:00:00Z"), FD)
    validate_error(res, "ERR_COURT_NOT_AVAILABLE")


def test_booking_allowed_once_court_reopened():
    """PRD §3.1: "Returning a court to service moves it MAINTENANCE → AVAILABLE, and
    requires the court to currently be in MAINTENANCE."
    PRD §3.3: "The court must be AVAILABLE, else ERR_COURT_NOT_AVAILABLE".

    Design: Difficulty/cross_entity_state_dependency/xdep_reservation_requires_court_available
    """
    s = setup_booking_scenario()
    get_success_data(api_client.court_maintenance(s["court"]["id"], FD))
    get_success_data(api_client.court_reopen(s["court"]["id"], FD))
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-09T10:00:00Z", "2026-05-09T11:00:00Z")
    assert res["status"] == "BOOKED"


# ─── Corner: booking_in_past_rejected ─────────────────────────────────
def test_booking_in_past_rejected():
    """PRD §3.3: "The start_time must be strictly after the current clock, else
    ERR_BOOKING_IN_PAST".

    Design: Corner/validations/booking_in_past_rejected
    """
    s = setup_booking_scenario()
    set_clock("2026-05-10T00:00:00Z")
    res = api_client.create_reservation(
        create_reservation_payload(s["court"]["id"], s["member"]["id"],
                                   "2026-05-05T10:00:00Z", "2026-05-05T11:00:00Z"), FD)
    validate_error(res, "ERR_BOOKING_IN_PAST")


# ─── Corner: booking_window_exceeded_rejected ─────────────────────────
def test_booking_beyond_advance_window_rejected():
    """PRD §3.3: "no more than 14 days ahead of the current clock, else
    ERR_BOOKING_WINDOW_EXCEEDED".

    Design: Corner/validations/booking_window_exceeded_rejected
    """
    s = setup_booking_scenario()  # clock at default 2026-05-01
    res = api_client.create_reservation(
        create_reservation_payload(s["court"]["id"], s["member"]["id"],
                                   "2026-05-20T10:00:00Z", "2026-05-20T11:00:00Z"), FD)
    validate_error(res, "ERR_BOOKING_WINDOW_EXCEEDED")


# ─── Corner: checkin_outside_window_rejected ──────────────────────────
def test_checkin_outside_window_rejected():
    """PRD §3.3: "must occur while the current clock is within the window from 30
    minutes before start_time up to (but not including) end_time; outside that window
    it is rejected with ERR_CHECKIN_WINDOW."

    Design: Corner/validations/checkin_outside_window_rejected
    """
    s = setup_booking_scenario()
    res = make_reservation(s["court"]["id"], s["member"]["id"],
                           "2026-05-14T10:00:00Z", "2026-05-14T11:00:00Z")
    # clock still at default 2026-05-01, far before the [start-30m, end) window
    resp = api_client.checkin_reservation(res["id"], {}, FD)
    validate_error(resp, "ERR_CHECKIN_WINDOW")
