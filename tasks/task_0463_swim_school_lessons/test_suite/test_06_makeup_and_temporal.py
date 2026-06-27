"""Temporal-overlap geometry (instructor closed+buffer vs makeup half-open),
makeup-credit expiry boundary, credit-balance conservation across redeem+cancel,
and makeup booking constraints.

Difficulty queue (A): resource_temporal_overlap, boundary_precision (credit
expiry), compensating_invariant (credit balance).
Corner queue (B): calculations + errors makeup instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    assert_makeup_credit,
    TEST_USERS,
    make_parent_headers,
    set_clock,
    create_location,
    create_level,
    create_instructor,
    create_class_session,
    open_session,
    create_parent,
    create_student,
    setup_parent_with_student,
    setup_open_session,
    create_active_enrollment,
    create_makeup_booking_payload,
    pause_enrollment,
    issued_skip_credit,
    list_issued_credits,
    setup_skip_credit_via_pause,
    book_makeup,
    get_session_version,
)

ADMIN = TEST_USERS["school_admin_headers"]


# ─── resource_temporal_overlap: instructor closed interval + 15min buffer ──
def test_instructor_schedule_conflict_within_buffer(api):
    """PRD §3.4: "a conflict exists when the candidate's `start_minute` is earlier
    than the other session's `end_minute` plus the fifteen-minute buffer, and
    simultaneously the other session's `start_minute` is earlier than the
    candidate's `end_minute` plus the fifteen-minute buffer. Any such overlap
    rejects the open with `ERR_INSTRUCTOR_SCHEDULE_CONFLICT`."

    Coach A has an OPEN Tue 10:00-10:45 (600-645) session; a second Tue
    10:55-11:40 (655-700) session for the same coach sits only 10 minutes after
    the first ends (< 15 buffer), so the open is rejected.

    Design: Difficulty/resource_temporal_overlap/instructor_schedule_conflict_within_buffer
    """
    set_clock("2026-01-05T00:00:00Z")
    location = create_location()
    level = create_level(min_age_months=36, max_age_months=200,
                         max_students_per_instructor=4)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    sess_a = create_class_session(location["id"], level["id"], instructor["id"],
                                  lane_number=1, day_of_week=1,
                                  start_minute=600, end_minute=645)
    open_session(sess_a["id"])
    sess_b = create_class_session(location["id"], level["id"], instructor["id"],
                                  lane_number=2, day_of_week=1,
                                  start_minute=655, end_minute=700)
    res = api.open_class_session(sess_b["id"], ADMIN)
    validate_error(res, "ERR_INSTRUCTOR_SCHEDULE_CONFLICT")


def test_makeup_same_day_half_open_overlap_conflict(api):
    """PRD §3.8: "for every other of that student's bookings in `BOOKED` or
    `ATTENDED` status whose `occurrence_date` matches, a conflict exists when this
    booking's `occurrence_start_minute` is earlier than the other's
    `occurrence_end_minute` and the other's `occurrence_start_minute` is earlier
    than this booking's `occurrence_end_minute` — a half-open interval comparison
    with no buffer — and any such overlap is rejected with
    `ERR_MAKEUP_TIME_CONFLICT`."

    A student books S1 (10:00-10:45) then S2 (10:40-11:25) on the same date; the
    intervals overlap by 5 minutes, so the second booking is rejected.

    Design: Difficulty/resource_temporal_overlap/makeup_same_day_half_open_no_buffer_conflict
    """
    set_clock("2026-06-01T00:00:00Z")
    location = create_location()
    level = create_level(min_age_months=36, max_age_months=200,
                         max_students_per_instructor=4)
    inst_a = create_instructor(full_name="Coach A", certified_level_ids=[level["id"]])
    inst_b = create_instructor(full_name="Coach B", certified_level_ids=[level["id"]])
    src = create_class_session(location["id"], level["id"], inst_a["id"],
                               lane_number=1, day_of_week=1,
                               start_minute=600, end_minute=645)
    src = open_session(src["id"])
    s2_sess = create_class_session(location["id"], level["id"], inst_b["id"],
                                   lane_number=2, day_of_week=1,
                                   start_minute=640, end_minute=685)
    open_session(s2_sess["id"])
    parent, student = setup_parent_with_student(level["id"])
    # Two SKIP credits via pause/resume/pause.
    enr = create_active_enrollment(parent, student, src)
    pause_enrollment(parent, enr["id"])
    headers = make_parent_headers(parent["id"])
    validate_success(api.resume_enrollment(enr["id"], headers), 200)
    pause_enrollment(parent, enr["id"])
    credits = list_issued_credits(student["id"])
    assert len(credits) >= 2, f"expected 2 issued credits, got {len(credits)}"
    # Book the first occurrence, then attempt the overlapping second.
    book_makeup(parent, credits[0]["id"], src["id"], "2026-06-09T00:00:00Z")
    res = api.create_makeup_booking(
        create_makeup_booking_payload(credits[1]["id"], s2_sess["id"],
                                      "2026-06-09T00:00:00Z"),
        headers,
    )
    validate_error(res, "ERR_MAKEUP_TIME_CONFLICT")


def test_instructor_schedule_no_conflict_at_buffer_boundary(api):
    """PRD §3.4: "a conflict exists when the candidate's `start_minute` is earlier
    than the other session's `end_minute` plus the fifteen-minute buffer, and
    simultaneously the other session's `start_minute` is earlier than the
    candidate's `end_minute` plus the fifteen-minute buffer."

    Closed-interval+buffer geometry, exclusive side: a second same-instructor
    same-weekday session starting exactly 15 minutes after the first ends
    (start 660 == 645 + 15, so candidate.start is NOT earlier than other.end +
    buffer) does not conflict, so the open succeeds.

    Design: Difficulty/resource_temporal_overlap/instructor_schedule_conflict_within_buffer
    """
    set_clock("2026-01-05T00:00:00Z")
    location = create_location()
    level = create_level(min_age_months=36, max_age_months=200,
                         max_students_per_instructor=4)
    instructor = create_instructor(certified_level_ids=[level["id"]])
    sess_a = create_class_session(location["id"], level["id"], instructor["id"],
                                  lane_number=1, day_of_week=1,
                                  start_minute=600, end_minute=645)
    open_session(sess_a["id"])
    sess_b = create_class_session(location["id"], level["id"], instructor["id"],
                                  lane_number=2, day_of_week=1,
                                  start_minute=660, end_minute=705)
    opened = validate_success(api.open_class_session(sess_b["id"], ADMIN), 200)
    assert opened["status"] == "OPEN"


def test_makeup_same_day_back_to_back_allowed(api):
    """PRD §3.8: "this booking's `occurrence_start_minute` is earlier than the
    other's `occurrence_end_minute` and the other's `occurrence_start_minute` is
    earlier than this booking's `occurrence_end_minute` — a half-open interval
    comparison with no buffer"

    Half-open geometry, no buffer: a second booking that starts exactly when the
    first ends (start 645 == other.end 645, so it is NOT earlier than the other's
    end) does not overlap, so the back-to-back booking succeeds.

    Design: Difficulty/resource_temporal_overlap/makeup_same_day_half_open_no_buffer_conflict
    """
    set_clock("2026-06-01T00:00:00Z")
    location = create_location()
    level = create_level(min_age_months=36, max_age_months=200,
                         max_students_per_instructor=4)
    inst_a = create_instructor(full_name="Coach A", certified_level_ids=[level["id"]])
    inst_b = create_instructor(full_name="Coach B", certified_level_ids=[level["id"]])
    src = create_class_session(location["id"], level["id"], inst_a["id"],
                               lane_number=1, day_of_week=1,
                               start_minute=600, end_minute=645)
    src = open_session(src["id"])
    s2_sess = create_class_session(location["id"], level["id"], inst_b["id"],
                                   lane_number=2, day_of_week=1,
                                   start_minute=645, end_minute=690)
    open_session(s2_sess["id"])
    parent, student = setup_parent_with_student(level["id"])
    enr = create_active_enrollment(parent, student, src)
    pause_enrollment(parent, enr["id"])
    headers = make_parent_headers(parent["id"])
    validate_success(api.resume_enrollment(enr["id"], headers), 200)
    pause_enrollment(parent, enr["id"])
    credits = list_issued_credits(student["id"])
    assert len(credits) >= 2, f"expected 2 issued credits, got {len(credits)}"
    book_makeup(parent, credits[0]["id"], src["id"], "2026-06-09T00:00:00Z")
    second = book_makeup(parent, credits[1]["id"], s2_sess["id"],
                         "2026-06-09T00:00:00Z")
    assert second["status"] == "BOOKED"


# ─── boundary_precision: credit expiry instant ─────────────────────────────
def test_credit_expired_at_exact_expiry_instant(api):
    """PRD §3.8: "the credit is considered expired the moment the current logical
    instant reaches or passes `expires_at` — the boundary instant itself counts
    as expired."

    A SKIP credit issued 2026-06-01 expires at 2026-07-31T00:00:00Z (60 days);
    redeeming with the clock at exactly that instant is rejected
    ERR_CREDIT_EXPIRED.

    Design: Difficulty/boundary_precision_check/makeup_credit_expiry_instant_boundary
    """
    env = setup_skip_credit_via_pause(clock="2026-06-01T00:00:00Z")
    set_clock("2026-07-31T00:00:00Z")
    headers = make_parent_headers(env["parent"]["id"])
    res = api.create_makeup_booking(
        create_makeup_booking_payload(env["credit"]["id"], env["session"]["id"],
                                      "2026-08-04T00:00:00Z"),
        headers,
    )
    validate_error(res, "ERR_CREDIT_EXPIRED")


def test_credit_redeemable_before_expiry_instant(api):
    """PRD §3.8: "Redemption checks the credit first: the current instant must be
    before `expires_at`, or the booking is rejected with `ERR_CREDIT_EXPIRED`"

    With the clock still before 2026-07-31 (the credit's expires_at), the same
    SKIP credit redeems into a booking — confirming the boundary is exclusive on
    the redeemable side.

    Design: Difficulty/boundary_precision_check/makeup_credit_expiry_instant_boundary
    """
    env = setup_skip_credit_via_pause(clock="2026-06-01T00:00:00Z")
    set_clock("2026-07-30T00:00:00Z")
    booking = book_makeup(env["parent"], env["credit"]["id"], env["session"]["id"],
                          "2026-08-04T00:00:00Z")
    assert booking["status"] == "BOOKED"


# ─── compensating_invariant: credit balance across redeem+cancel ───────────
def test_cancel_booking_restores_credit_to_issued(api):
    """PRD §3.8: "cancellation moves the booking to `CANCELLED` and restores its
    credit from `REDEEMED` back to `ISSUED`, conserving the credit with no
    balance drift."

    Booking a SKIP credit (-> REDEEMED) then cancelling restores the credit to
    ISSUED and the booking is CANCELLED.

    Design: Difficulty/compensating_invariant/makeup_credit_balance_conserved_after_redeem_and_cancel
    """
    env = setup_skip_credit_via_pause(clock="2026-06-01T00:00:00Z")
    booking = book_makeup(env["parent"], env["credit"]["id"], env["session"]["id"],
                          "2026-06-09T00:00:00Z")
    headers = make_parent_headers(env["parent"]["id"])
    cancelled = validate_success(api.cancel_makeup_booking(booking["id"], headers), 200)
    assert cancelled["status"] == "CANCELLED"
    credit = validate_success(api.get_makeup_credit(env["credit"]["id"], ADMIN), 200)
    assert credit["status"] == "ISSUED"


def test_credit_issued_balance_conserved_after_redeem_and_cancel(api):
    """PRD §3.8: "The `ISSUED`-to-`REDEEMED`-to-`ISSUED` path is therefore a
    conservation cycle that holds only while the credit remains within its
    validity window and the redemption has not been finalized by attendance or
    no-show."

    The student's count of ISSUED credits returns to exactly 1 after a redeem
    (booking) then its compensating cancel — zero drift.

    Design: Difficulty/compensating_invariant/makeup_credit_balance_conserved_after_redeem_and_cancel
    """
    env = setup_skip_credit_via_pause(clock="2026-06-01T00:00:00Z")
    booking = book_makeup(env["parent"], env["credit"]["id"], env["session"]["id"],
                          "2026-06-09T00:00:00Z")
    headers = make_parent_headers(env["parent"]["id"])
    validate_success(api.cancel_makeup_booking(booking["id"], headers), 200)
    issued = list_issued_credits(env["student"]["id"])
    assert len(issued) == 1, (
        f"ISSUED credit balance must conserve to 1, got {len(issued)}"
    )


# ─── Corner queue (B): makeup booking constraints ──────────────────────────
def test_makeup_occurrence_full_rejected(api):
    """PRD §3.8: "the remaining room equals the session's `capacity` minus its
    `enrolled_count` minus the count of bookings already in `BOOKED` status for
    that session on that date, and if the remaining room is zero or less the
    booking is rejected with `ERR_MAKEUP_OCCURRENCE_FULL`."

    A capacity-1 target session whose only seat is held by an ACTIVE enrollment
    leaves remaining = 1 - 1 - 0 = 0, so a makeup booking into it is rejected.

    Design: Corner/calculations/makeup_occurrence_full_rejects_booking
    """
    set_clock("2026-06-01T00:00:00Z")
    location = create_location()
    level = create_level(name="Solo", min_age_months=36, max_age_months=200,
                         max_students_per_instructor=1)
    inst_a = create_instructor(full_name="Coach A", certified_level_ids=[level["id"]])
    inst_b = create_instructor(full_name="Coach B", certified_level_ids=[level["id"]])
    target = create_class_session(location["id"], level["id"], inst_a["id"],
                                  lane_number=1, day_of_week=1,
                                  start_minute=600, end_minute=645)
    target = open_session(target["id"])
    src = create_class_session(location["id"], level["id"], inst_b["id"],
                               lane_number=2, day_of_week=2,
                               start_minute=600, end_minute=645)
    src = open_session(src["id"])
    # P1/S1 fills the target's only seat.
    p1 = create_parent(full_name="P1", email="p1@x.com")
    s1 = create_student(p1, level["id"], full_name="S1")
    create_active_enrollment(p1, s1, target)
    # P2/S2 earns a SKIP credit and tries to book the full target occurrence.
    p2 = create_parent(full_name="P2", email="p2@x.com")
    s2 = create_student(p2, level["id"], full_name="S2")
    enr2 = create_active_enrollment(p2, s2, src)
    pause_enrollment(p2, enr2["id"])
    credit = issued_skip_credit(s2["id"])
    headers2 = make_parent_headers(p2["id"])
    res = api.create_makeup_booking(
        create_makeup_booking_payload(credit["id"], target["id"],
                                      "2026-06-09T00:00:00Z"),
        headers2,
    )
    validate_error(res, "ERR_MAKEUP_OCCURRENCE_FULL")


def test_credit_not_redeemable_when_already_redeemed(api):
    """PRD §3.8: "the credit must be in `ISSUED` status, or it is rejected with
    `ERR_CREDIT_NOT_REDEEMABLE`."

    Booking a second makeup against a credit already REDEEMED by a live BOOKED
    booking is rejected ERR_CREDIT_NOT_REDEEMABLE.

    Design: Corner/errors/credit_not_redeemable_when_already_redeemed
    """
    env = setup_skip_credit_via_pause(clock="2026-06-01T00:00:00Z")
    book_makeup(env["parent"], env["credit"]["id"], env["session"]["id"],
                "2026-06-09T00:00:00Z")
    headers = make_parent_headers(env["parent"]["id"])
    res = api.create_makeup_booking(
        create_makeup_booking_payload(env["credit"]["id"], env["session"]["id"],
                                      "2026-06-16T00:00:00Z"),
        headers,
    )
    validate_error(res, "ERR_CREDIT_NOT_REDEEMABLE")
