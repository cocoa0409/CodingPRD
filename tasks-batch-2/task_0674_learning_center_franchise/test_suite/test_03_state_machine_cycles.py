"""Non-linear state machines: the worksheet retry cycle (ASSIGNED -> GRADED ->
RETRY -> ASSIGNED -> GRADED -> MASTERED) and the session/attendance fork-join where
closing resolves remaining BOOKED seats to ABSENT.

Queue A — Difficulty/non_linear_state_machine.
"""
from test_helpers import (
    validate_success,
    setup_active_enrollment_with_worksheet, setup_active_enrollment,
    create_student, create_and_place_enrollment, create_and_open_session, book_seat,
    set_clock, make_center_director_headers, make_instructor_headers,
)
from test_helpers import api_client as api

DIRECTOR = make_center_director_headers()
INSTRUCTOR = make_instructor_headers()


# ===========================================================================
# worksheet_retry_cycle_graded_back_to_assigned
# ===========================================================================
def test_failing_grade_moves_worksheet_to_retry():
    """PRD §3.4: "Immediately after grading, the system resolves the graded set: if the
    `score` is greater than or equal to the targeted level's `mastery_score_threshold`,
    the set advances from `GRADED` to `MASTERED`; otherwise it moves from `GRADED` to
    `RETRY`."

    A score of 70 below threshold 80 -> RETRY, attempt_count 1.

    Design: Difficulty/non_linear_state_machine/worksheet_retry_cycle_graded_back_to_assigned
    """
    *_rest, ws = setup_active_enrollment_with_worksheet(mastery_score_threshold=80)
    graded = validate_success(api.grade_worksheet(ws["id"], {"score": 70}, INSTRUCTOR))
    assert graded["status"] == "RETRY", f"score 70 < 80 -> RETRY, got {graded['status']}"
    assert graded["attempt_count"] == 1


def test_retry_reassign_then_pass_completes_cycle_and_counts_two_attempts():
    """PRD §3.4: "A set that reaches `RETRY` can be reassigned by an instructor ...
    which returns it from `RETRY` to `ASSIGNED`, resets its `score` to null so the next
    grade re-attempts the same `set_number`, and increments its `version`."
    PRD §3.4: "Grading records the `score`, increments `attempt_count` by one, moves the
    set from `ASSIGNED` to `GRADED`, and increments the worksheet's `version`."

    Fail (70) -> RETRY -> reassign -> ASSIGNED -> pass (90) -> MASTERED; the same
    set_number is revisited and attempt_count reaches 2.

    Design: Difficulty/non_linear_state_machine/worksheet_retry_cycle_graded_back_to_assigned
    """
    *_rest, ws = setup_active_enrollment_with_worksheet(mastery_score_threshold=80,
                                                        worksheets_to_master=2)
    fail = validate_success(api.grade_worksheet(ws["id"], {"score": 70}, INSTRUCTOR))
    assert fail["status"] == "RETRY"

    reassigned = validate_success(api.reassign_worksheet(ws["id"], INSTRUCTOR))
    assert reassigned["status"] == "ASSIGNED", "RETRY -> ASSIGNED after reassign"
    assert reassigned["score"] is None, "score reset to null on reassign"

    passed = validate_success(api.grade_worksheet(ws["id"], {"score": 90}, INSTRUCTOR))
    assert passed["status"] == "MASTERED", "second grade 90 >= 80 -> MASTERED"
    assert passed["attempt_count"] == 2, \
        f"two grades of the same set -> attempt_count 2, got {passed['attempt_count']}"


# ===========================================================================
# session_attendance_fork_join_close_resolves_booked_to_absent
# ===========================================================================
def _setup_session_two_booked():
    """OPERATING center + two ACTIVE enrollments + an OPEN session (cap 6, 09:00-10:00)
    with two BOOKED attendance records. Clock starts 08:00. Returns (center, session,
    ar1, ar2)."""
    center, subject, _level, family, _student, en1 = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    st2 = create_student(family["id"], full_name="K2", birthdate="2017-01-01T00:00:00Z")
    en2 = create_and_place_enrollment(center["id"], st2["id"], subject["id"])
    session = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                      "2026-05-01T10:00:00Z", 6)
    ar1 = book_seat(session["id"], en1["id"])
    ar2 = book_seat(session["id"], en2["id"])
    return center, session, ar1, ar2


def test_checked_in_seat_stays_present_through_close():
    """PRD §3.5: "Checking in moves a record from `BOOKED` to `PRESENT` and sets
    `marked_at` to the current clock, permitted only while the parent session is `OPEN`"
    PRD §3.5: "on close, every attendance record still in `BOOKED` status is driven to
    `ABSENT` with its `marked_at` set to the current clock"

    A record that was checked in to PRESENT is not in BOOKED at close, so close leaves
    it PRESENT.

    Design: Difficulty/non_linear_state_machine/session_attendance_fork_join_close_resolves_booked_to_absent
    """
    _c, session, ar1, _ar2 = _setup_session_two_booked()
    validate_success(api.check_in_attendance(ar1["id"], INSTRUCTOR))
    set_clock("2026-05-01T09:30:00Z")
    validate_success(api.close_session(session["id"], DIRECTOR))
    fetched = validate_success(api.get_attendance_record(ar1["id"], DIRECTOR))
    assert fetched["status"] == "PRESENT", "checked-in seat remains PRESENT after close"


def test_close_resolves_remaining_booked_seat_to_absent_and_recounts():
    """PRD §3.5: "on close, every attendance record still in `BOOKED` status is driven
    to `ABSENT` with its `marked_at` set to the current clock, and the session's
    `version` is incremented."
    PRD §3.5: "`booked_seat_count` is the number of attendance records on the session
    whose status is `BOOKED` or `PRESENT`."

    Of two seats, one checked in (PRESENT) and one left BOOKED; closing drives the
    remaining BOOKED seat to ABSENT, leaving booked_seat_count at 1 (the PRESENT seat).

    Design: Difficulty/non_linear_state_machine/session_attendance_fork_join_close_resolves_booked_to_absent
    """
    _c, session, ar1, ar2 = _setup_session_two_booked()
    validate_success(api.check_in_attendance(ar1["id"], INSTRUCTOR))
    set_clock("2026-05-01T09:30:00Z")
    closed = validate_success(api.close_session(session["id"], DIRECTOR))
    assert closed["status"] == "CLOSED"

    resolved = validate_success(api.get_attendance_record(ar2["id"], DIRECTOR))
    assert resolved["status"] == "ABSENT", "remaining BOOKED seat -> ABSENT on close"
    fresh_session = validate_success(api.get_session(session["id"], DIRECTOR))
    assert fresh_session["booked_seat_count"] == 1, \
        f"only the PRESENT seat counts -> 1, got {fresh_session['booked_seat_count']}"
