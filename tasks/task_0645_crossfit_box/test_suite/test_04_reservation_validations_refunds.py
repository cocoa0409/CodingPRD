"""Reservation pre-checks, the late-cancel refund window, validation-priority
conflicts, and coach/member temporal-overlap rules.

Queue A: refund_on_cancel timely-vs-late, late-cancel exact-12h boundary,
priority-pair conflicts (safety>temporal, referential>fiscal), cross-entity
state dependencies (suspension, completed session), resource temporal overlap
(coach buffer-inclusive, member bare-window).
Queue B: foundations block/pass, drop-in-competition, duplicate reservation,
window-closed-after-cutoff, no-punches, drop-in-with-membership shape.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_member_headers, make_coach_headers,
    set_clock, create_coach, create_track, create_unlimited_plan,
    create_punch_plan, register_member, create_session,
    create_active_membership, create_membership, confirm_payment,
    complete_foundations, reserve,
    setup_drop_in_reserved_seat, setup_suspended_member,
    setup_member_with_active_membership,
)

BOX = TEST_USERS["box_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ==========================================================================
# Queue A — dual_variant_calc / refund_on_cancel_timely_vs_late_reservation_domain
# ==========================================================================

def test_drop_in_cancel_exactly_12h_before_refunds_fee(api):
    """PRD §3.5: "If the gap is at least 12 hours the cancel is timely — the punch is restored (the membership's `punches_remaining` is increased by one when `punch_consumed` was true) and the drop-in fee is fully refunded (the recorded `drop_in_fee_charged_cents` is returned)."
    PRD §3.5: "The boundary is inclusive on the timely side: a cancel exactly 12 hours before start is treated as timely and earns the refund."

    Design: Difficulty/dual_variant_calc/refund_on_cancel_timely_vs_late_reservation_domain
    """
    s = setup_drop_in_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                                    clock_before="2026-06-01T00:00:00Z",
                                    drop_in_fee_cents=2500)
    set_clock("2026-06-10T06:00:00Z")  # exactly 12h before 18:00
    resp = api.cancel_reservation(s["reservation"]["id"],
                                  make_member_headers(s["visitor"]["id"]))
    rv = validate_success(resp)
    assert rv["status"] == "CANCELLED"
    assert rv["drop_in_fee_charged_cents"] == 0


def test_drop_in_cancel_11h_before_forfeits_fee(api):
    """PRD §3.5: "If that gap is strictly less than 12 hours the cancel is late and
    the athlete forfeits — the punch stays consumed and the drop-in fee is not
    refunded."

    Design: Difficulty/dual_variant_calc/refund_on_cancel_timely_vs_late_reservation_domain
    """
    s = setup_drop_in_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                                    clock_before="2026-06-01T00:00:00Z",
                                    drop_in_fee_cents=2500)
    set_clock("2026-06-10T07:00:00Z")  # 11h before 18:00 -> late
    resp = api.cancel_reservation(s["reservation"]["id"],
                                  make_member_headers(s["visitor"]["id"]))
    rv = validate_success(resp)
    assert rv["status"] == "CANCELLED"
    assert rv["drop_in_fee_charged_cents"] == 2500


# ==========================================================================
# Queue A — boundary_precision_check / late_cancel_window_exact_12h_is_timely_refund
# ==========================================================================

def test_late_cancel_window_boundary_12h_is_timely(api):
    """PRD §3.5: "The boundary is inclusive on the timely side: a cancel exactly
    12 hours before start is treated as timely and earns the refund."

    Design: Difficulty/boundary_precision_check/late_cancel_window_exact_12h_is_timely_refund
    """
    s = setup_drop_in_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                                    clock_before="2026-06-01T00:00:00Z",
                                    drop_in_fee_cents=2500)
    set_clock("2026-06-10T06:00:00Z")  # exactly 12h
    resp = api.cancel_reservation(s["reservation"]["id"],
                                  make_member_headers(s["visitor"]["id"]))
    rv = validate_success(resp)
    assert rv["drop_in_fee_charged_cents"] == 0
    assert rv["status"] == "CANCELLED"


def test_late_cancel_window_just_inside_forfeits(api):
    """PRD §3.5: "If that gap is strictly less than 12 hours the cancel is late and
    the athlete forfeits — the punch stays consumed and the drop-in fee is not
    refunded."

    Design: Difficulty/boundary_precision_check/late_cancel_window_exact_12h_is_timely_refund
    """
    s = setup_drop_in_reserved_seat(session_starts_at="2026-06-10T18:00:00Z",
                                    clock_before="2026-06-01T00:00:00Z",
                                    drop_in_fee_cents=2500)
    set_clock("2026-06-10T06:01:00Z")  # 11h59m before -> strictly inside window
    resp = api.cancel_reservation(s["reservation"]["id"],
                                  make_member_headers(s["visitor"]["id"]))
    rv = validate_success(resp)
    assert rv["drop_in_fee_charged_cents"] == 2500


# ==========================================================================
# Queue A — priority_pair_validation_conflict
#   safety_vs_temporal_suspension_wins_over_window_closed
# ==========================================================================

def test_suspension_priority_over_window_closed(api):
    """PRD §3.4: "Next, the booking member must not be reservation-suspended — a member whose `no_show_strikes` is at least 3 is blocked with `ERR_RESERVATION_SUSPENDED`."
    PRD §3.4: "Next the reservation window is enforced: the session must be `SCHEDULED` and the current clock time must be at or before the session's `starts_at` minus 60 minutes — the cut-off is 60 minutes before the session begins, so a request exactly at `starts_at` minus 60 minutes is still open while any later moment is closed — and a violation yields `ERR_RESERVATION_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_suspension_wins_over_window_closed
    """
    s = setup_suspended_member(clock_setup="2026-06-01T00:00:00Z",
                               clock_after_complete="2026-06-05T00:00:00Z")
    coach_id = s["coach"]["id"]
    track_id = s["track"]["id"]
    member = s["member"]
    membership = s["membership"]

    # confirm the member is suspended
    m_after = validate_success(api.get_member(member["id"], BOX))
    assert m_after["no_show_strikes"] == 3
    assert m_after["reservation_suspended"] is True

    # target session created then CANCELLED (status != SCHEDULED)
    tgt = create_session(track_id, coach_id, "2026-06-20T18:00:00Z", capacity=3)
    validate_success(api.cancel_session(tgt["id"], make_coach_headers(coach_id)))
    tgt_now = validate_success(api.get_session(tgt["id"], BOX))

    resp = api.create_reservation(
        {"session_id": tgt["id"], "member_id": member["id"],
         "membership_id": membership["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": tgt_now["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESERVATION_SUSPENDED.value)


def test_suspension_over_window_closed_returns_409_status(api):
    """PRD §2.10: "Domain-specific business rules — membership ownership of a reservation, reservation suspension, foundations prerequisites, reservation windows, drop-in eligibility, duplicate and time-conflict checks, coach double-booking, punch availability, roster capacity, coach certification — are evaluated after that."
    PRD §3.4: "a member whose `no_show_strikes` is at least 3 is blocked with `ERR_RESERVATION_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_temporal_suspension_wins_over_window_closed
    """
    s = setup_suspended_member(clock_setup="2026-06-01T00:00:00Z",
                               clock_after_complete="2026-06-05T00:00:00Z")
    coach_id = s["coach"]["id"]
    track_id = s["track"]["id"]
    member = s["member"]
    membership = s["membership"]

    # Target session whose reservation window is also closed: complete it so it
    # is no longer SCHEDULED (window-closed condition) — suspension must still win.
    tgt = create_session(track_id, coach_id, "2026-06-06T18:00:00Z", capacity=3)
    set_clock("2026-06-06T18:30:00Z")
    validate_success(api.complete_session(tgt["id"], {"attendance": {}},
                                          make_coach_headers(coach_id)))
    tgt_now = validate_success(api.get_session(tgt["id"], BOX))

    resp = api.create_reservation(
        {"session_id": tgt["id"], "member_id": member["id"],
         "membership_id": membership["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": tgt_now["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESERVATION_SUSPENDED.value)
    assert resp.status_code == 409


# ==========================================================================
# Queue A — priority_pair_validation_conflict
#   referential_vs_fiscal_membership_not_owned_wins_over_no_punches
# ==========================================================================

def test_membership_not_owned_priority_over_no_punches(api):
    """PRD §3.4: "for a `MEMBERSHIP` reservation, the supplied `membership_id` must belong to a membership whose `member_id` equals the reserving `member_id`, or the request is rejected with `ERR_MEMBERSHIP_NOT_OWNED`."
    PRD §3.4: "For a `PUNCH`-plan `MEMBERSHIP` reservation, the consuming membership must have `punches_remaining` of at least 1 at commit time (that is, when the seat is actually granted as `RESERVED`, not when it is merely waitlisted), or the booking is rejected with `ERR_NO_PUNCHES_REMAINING`."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_membership_not_owned_wins_over_no_punches
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_punch_plan(punch_count=1, monthly_fee_cents=0,
                             requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")

    # owner depletes their single punch on a session
    depl_sess = create_session(track["id"], coach["id"], "2026-06-05T18:00:00Z", capacity=3)
    owner = register_member()
    ms_owner = create_active_membership(owner["id"], plan["id"])
    reserve(depl_sess["id"], owner["id"], depl_sess["version"],
            membership_id=ms_owner["id"], reservation_kind="MEMBERSHIP")

    # attacker tries to reserve a future session citing owner's depleted membership
    other = register_member()
    coach2 = create_coach(certified=True)
    track2 = create_track(coach2["id"], track_type="REGULAR")
    tgt = create_session(track2["id"], coach2["id"], "2026-06-12T18:00:00Z", capacity=3)

    resp = api.create_reservation(
        {"session_id": tgt["id"], "member_id": other["id"],
         "membership_id": ms_owner["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": tgt["version"]},
        make_member_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_OWNED.value)


def test_membership_not_owned_with_punches_remaining_still_blocks(api):
    """PRD §3.4: "for a `MEMBERSHIP` reservation, the supplied `membership_id` must belong to a membership whose `member_id` equals the reserving `member_id`, or the request is rejected with `ERR_MEMBERSHIP_NOT_OWNED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_membership_not_owned_wins_over_no_punches
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_punch_plan(punch_count=5, monthly_fee_cents=0,
                             requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-12T18:00:00Z", capacity=3)

    owner = register_member()
    ms_owner = create_active_membership(owner["id"], plan["id"])  # punches NOT depleted
    other = register_member()

    # Attacker cites owner's membership (which has punches): the not-owned rule
    # (priority 8) must reject before any fiscal check.
    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": other["id"],
         "membership_id": ms_owner["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": session["version"]},
        make_member_headers(other["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBERSHIP_NOT_OWNED.value)


# ==========================================================================
# Queue A — cross_entity_state_dependency / reservation_blocked_by_member_suspension_state
# ==========================================================================

def test_reservation_blocked_by_member_suspension(api):
    """PRD §3.1: "The computed `reservation_suspended` flag is true exactly when `no_show_strikes` is at least 3 — the suspension threshold — and false otherwise; while it is true, the member may create no new reservations."
    PRD §3.4: "a member whose `no_show_strikes` is at least 3 is blocked with `ERR_RESERVATION_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_member_suspension_state
    """
    s = setup_suspended_member(clock_setup="2026-06-01T00:00:00Z",
                               clock_after_complete="2026-06-05T00:00:00Z")
    coach_id = s["coach"]["id"]
    track_id = s["track"]["id"]
    member = s["member"]
    membership = s["membership"]

    m_after = validate_success(api.get_member(member["id"], BOX))
    assert m_after["no_show_strikes"] == 3
    assert m_after["reservation_suspended"] is True

    tgt = create_session(track_id, coach_id, "2026-06-12T18:00:00Z", capacity=3)
    resp = api.create_reservation(
        {"session_id": tgt["id"], "member_id": member["id"],
         "membership_id": membership["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": tgt["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESERVATION_SUSPENDED.value)


def test_member_no_show_strikes_drive_reservation_suspended_flag(api):
    """PRD §3.1: "The computed `reservation_suspended` flag is true exactly when `no_show_strikes` is at least 3 — the suspension threshold — and false otherwise".
    PRD §3.5: "transitions from `RESERVED` to `NO_SHOW`, increments that member's `no_show_strikes` by one, and recomputes that member's `reservation_suspended` to reflect whether `no_show_strikes` has reached 3."

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_member_suspension_state
    """
    s = setup_suspended_member(clock_setup="2026-06-01T00:00:00Z",
                               clock_after_complete="2026-06-05T00:00:00Z")
    member = validate_success(api.get_member(s["member"]["id"], BOX))
    assert member["no_show_strikes"] == 3
    assert member["reservation_suspended"] is True


# ==========================================================================
# Queue A — cross_entity_state_dependency / reservation_blocked_by_session_completed_state
# ==========================================================================

def test_reservation_blocked_by_completed_session(api):
    """PRD §3.4: "Next the reservation window is enforced: the session must be `SCHEDULED` and the current clock time must be at or before the session's `starts_at` minus 60 minutes — the cut-off is 60 minutes before the session begins, so a request exactly at `starts_at` minus 60 minutes is still open while any later moment is closed — and a violation yields `ERR_RESERVATION_WINDOW_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_session_completed_state
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-02T18:00:00Z", capacity=3)
    set_clock("2026-06-02T18:30:00Z")
    validate_success(api.complete_session(session["id"], {"attendance": {}},
                                          make_coach_headers(coach["id"])))
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    sess_v = validate_success(api.get_session(session["id"], BOX))["version"]

    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": sess_v},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESERVATION_WINDOW_CLOSED.value)


def test_reservation_on_cancelled_session_blocked_by_window(api):
    """PRD §3.4: "Next the reservation window is enforced: the session must be `SCHEDULED` and the current clock time must be at or before the session's `starts_at` minus 60 minutes — the cut-off is 60 minutes before the session begins, so a request exactly at `starts_at` minus 60 minutes is still open while any later moment is closed — and a violation yields `ERR_RESERVATION_WINDOW_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/reservation_blocked_by_session_completed_state
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-20T18:00:00Z", capacity=3)
    # Box-cancel the session so it is no longer SCHEDULED.
    validate_success(api.cancel_session(session["id"], make_coach_headers(coach["id"])))
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    sess_v = validate_success(api.get_session(session["id"], BOX))["version"]

    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": sess_v},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESERVATION_WINDOW_CLOSED.value)


# ==========================================================================
# Queue A — resource_temporal_overlap / coach_double_booked_buffer_inclusive_overlap
# ==========================================================================

def test_coach_double_booked_within_turnaround_buffer(api):
    """PRD §3.4: "the system treats each of that coach's `SCHEDULED` sessions as occupying a busy interval that runs from its `starts_at` to its `starts_at` plus `duration_minutes` plus a 15-minute trailing turnaround buffer, and the new session's busy interval (computed the same way) must not overlap any of them — intervals that merely touch at their endpoints are allowed, but any genuine overlap is rejected with `ERR_COACH_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/coach_double_booked_buffer_inclusive_overlap
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    set_clock("2026-06-01T00:00:00Z")
    # first session 18:00-19:00, busy until 19:15 with buffer
    create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z",
                   duration_minutes=60, capacity=3)
    # second session at 19:10 starts inside the 19:15 buffer
    resp = api.create_session(
        {"track_id": track["id"], "coach_id": coach["id"],
         "starts_at": "2026-06-10T19:10:00Z", "duration_minutes": 60, "capacity": 3},
        make_coach_headers(coach["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COACH_DOUBLE_BOOKED.value)


def test_coach_session_touching_buffer_endpoint_allowed(api):
    """PRD §3.4: "the new session's busy interval (computed the same way) must not overlap any of them — intervals that merely touch at their endpoints are allowed, but any genuine overlap is rejected with `ERR_COACH_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/coach_double_booked_buffer_inclusive_overlap
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    set_clock("2026-06-01T00:00:00Z")
    # first session 18:00-19:00, busy until 19:15 (60min + 15min buffer)
    create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z",
                   duration_minutes=60, capacity=3)
    # second session starts exactly at 19:15 — touching the busy-interval endpoint
    resp = api.create_session(
        {"track_id": track["id"], "coach_id": coach["id"],
         "starts_at": "2026-06-10T19:15:00Z", "duration_minutes": 60, "capacity": 3},
        make_coach_headers(coach["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED"


# ==========================================================================
# Queue A — resource_temporal_overlap / member_session_time_conflict_no_buffer_disjoint
# ==========================================================================

def test_member_session_time_conflict_overlapping_reservations(api):
    """PRD §3.4: "the new reservation must not overlap in time with another non-terminal reservation the same member already holds: treating each reservation's session as occupying the half-open interval from its `starts_at` to its `starts_at` plus duration, these intervals must be disjoint, with intervals that merely touch at their endpoints allowed, and a genuine overlap yields `ERR_SESSION_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/member_session_time_conflict_no_buffer_disjoint
    """
    coach1 = create_coach(certified=True)
    coach2 = create_coach(certified=True)
    track1 = create_track(coach1["id"], track_type="REGULAR")
    track2 = create_track(coach2["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    sa = create_session(track1["id"], coach1["id"], "2026-06-10T18:00:00Z",
                        duration_minutes=60, capacity=3)
    sb = create_session(track2["id"], coach2["id"], "2026-06-10T18:30:00Z",
                        duration_minutes=60, capacity=3)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    reserve(sa["id"], member["id"], sa["version"],
            membership_id=ms["id"], reservation_kind="MEMBERSHIP")

    resp = api.create_reservation(
        {"session_id": sb["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": sb["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SESSION_TIME_CONFLICT.value)


def test_member_back_to_back_touching_sessions_allowed(api):
    """PRD §3.4: "treating each reservation's session as occupying the half-open interval from its `starts_at` to its `starts_at` plus duration, these intervals must be disjoint, with intervals that merely touch at their endpoints allowed".

    Design: Difficulty/resource_temporal_overlap/member_session_time_conflict_no_buffer_disjoint
    """
    coach1 = create_coach(certified=True)
    coach2 = create_coach(certified=True)
    track1 = create_track(coach1["id"], track_type="REGULAR")
    track2 = create_track(coach2["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    sa = create_session(track1["id"], coach1["id"], "2026-06-10T18:00:00Z",
                        duration_minutes=60, capacity=3)  # ends 19:00
    sb = create_session(track2["id"], coach2["id"], "2026-06-10T19:00:00Z",
                        duration_minutes=60, capacity=3)  # starts exactly at 19:00
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    reserve(sa["id"], member["id"], sa["version"],
            membership_id=ms["id"], reservation_kind="MEMBERSHIP")

    resp = api.create_reservation(
        {"session_id": sb["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": sb["version"]},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "RESERVED"


# ==========================================================================
# Queue B — validations
# ==========================================================================

def test_foundations_not_completed_blocks_regular_reservation(api):
    """PRD §3.4: "when the session's track is of type `REGULAR` and the consuming membership's plan has `requires_foundations` set, the membership's `foundations_completed` must be true, or the booking is rejected with `ERR_FOUNDATIONS_NOT_COMPLETED`."

    Design: Corner/validations/foundations_not_completed_blocks_regular_reservation
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=True)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=3)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])

    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": session["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FOUNDATIONS_NOT_COMPLETED.value)


def test_foundations_completed_allows_regular_reservation(api):
    """PRD §3.3: "a `Coach` completes a membership's foundations by referencing its `membership_id`, which sets the membership's `foundations_completed` to true".
    PRD §3.4: "when the session's track is of type `REGULAR` and the consuming membership's plan has `requires_foundations` set, the membership's `foundations_completed` must be true".

    Design: Corner/validations/foundations_completed_allows_regular_reservation
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=True)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=3)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    complete_foundations(ms["id"], coach["id"])

    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": session["version"]},
        make_member_headers(member["id"]),
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "RESERVED"


def test_drop_in_competition_session_returns_drop_in_not_allowed(api):
    """PRD §3.4: "a visiting or drop-in athlete — a member with `home_box_member` false booking a `DROP_IN` seat — may book only sessions whose track is not of type `COMPETITION`; an attempt on a competition-track session is rejected with `ERR_DROP_IN_NOT_ALLOWED`."

    Design: Corner/validations/drop_in_competition_session_returns_drop_in_not_allowed
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="COMPETITION", name="Comp")
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z",
                             capacity=5, drop_in_fee_cents=3000)
    visitor = register_member(home_box_member=False)

    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": visitor["id"],
         "reservation_kind": "DROP_IN", "expected_session_version": session["version"]},
        make_member_headers(visitor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DROP_IN_NOT_ALLOWED.value)


def test_duplicate_reservation_same_session_returns_duplicate(api):
    """PRD §3.4: "a member may hold at most one non-terminal (`RESERVED` or `WAITLISTED`) reservation on a given session; a second is rejected with `ERR_DUPLICATE_RESERVATION`."

    Design: Corner/validations/duplicate_reservation_same_session_returns_duplicate
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=5)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    reserve(session["id"], member["id"], session["version"],
            membership_id=ms["id"], reservation_kind="MEMBERSHIP")
    sess_v1 = validate_success(api.get_session(session["id"], BOX))["version"]

    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": sess_v1},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESERVATION.value)


def test_reservation_window_closed_after_cutoff(api):
    """PRD §3.4: "the current clock time must be at or before the session's `starts_at` minus 60 minutes — the cut-off is 60 minutes before the session begins, so a request exactly at `starts_at` minus 60 minutes is still open while any later moment is closed — and a violation yields `ERR_RESERVATION_WINDOW_CLOSED`."

    Design: Corner/validations/reservation_window_closed_after_cutoff_returns_error
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=5)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    set_clock("2026-06-10T17:01:00Z")  # 59 min before -> closed

    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": session["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESERVATION_WINDOW_CLOSED.value)


def test_no_punches_remaining_returns_error(api):
    """PRD §3.4: "For a `PUNCH`-plan `MEMBERSHIP` reservation, the consuming membership must have `punches_remaining` of at least 1 at commit time (that is, when the seat is actually granted as `RESERVED`, not when it is merely waitlisted), or the booking is rejected with `ERR_NO_PUNCHES_REMAINING`."

    Design: Corner/validations/no_punches_remaining_returns_error
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_punch_plan(punch_count=1, monthly_fee_cents=0,
                             requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    s1 = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z", capacity=5)
    s2 = create_session(track["id"], coach["id"], "2026-06-12T18:00:00Z", capacity=5)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])
    reserve(s1["id"], member["id"], s1["version"],
            membership_id=ms["id"], reservation_kind="MEMBERSHIP")

    resp = api.create_reservation(
        {"session_id": s2["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "MEMBERSHIP",
         "expected_session_version": s2["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_PUNCHES_REMAINING.value)


def test_drop_in_with_membership_id_returns_plan_shape_invalid(api):
    """PRD §3.4: "A `DROP_IN` reservation must omit `membership_id`, and a `MEMBERSHIP` reservation must supply it; violating this pairing is rejected with `ERR_PLAN_SHAPE_INVALID`."

    Design: Corner/validations/drop_in_with_membership_id_returns_plan_shape_invalid
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(commitment_months=0, requires_foundations=False)
    set_clock("2026-06-01T00:00:00Z")
    session = create_session(track["id"], coach["id"], "2026-06-10T18:00:00Z",
                             capacity=5, drop_in_fee_cents=2000)
    member = register_member()
    ms = create_active_membership(member["id"], plan["id"])

    resp = api.create_reservation(
        {"session_id": session["id"], "member_id": member["id"],
         "membership_id": ms["id"], "reservation_kind": "DROP_IN",
         "expected_session_version": session["version"]},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_SHAPE_INVALID.value)
