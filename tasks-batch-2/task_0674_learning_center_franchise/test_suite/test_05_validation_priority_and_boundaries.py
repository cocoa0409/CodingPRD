"""Validation-priority conflicts (which error wins when two rules fire) and numeric
boundary precision (mastery threshold at 79/80; empty-invoice zero-billable boundary).

Queue A — Difficulty/priority_pair_validation_conflict and
Difficulty/boundary_precision_check.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_active_enrollment, setup_operating_center_with_subject,
    create_subject, create_level, create_family, create_student,
    create_and_place_enrollment, create_enrollment, create_and_open_session, book_seat,
    create_invoice, set_clock,
    make_center_director_headers, make_instructor_headers,
)
from test_helpers import api_client as api

DIRECTOR = make_center_director_headers()
INSTRUCTOR = make_instructor_headers()


# ===========================================================================
# booking_invalid_state_beats_ratio_exceeded
# (state guard p6 ERR_INVALID_STATE pre-empts business p7 ERR_RATIO_EXCEEDED)
# ===========================================================================
def test_booking_closed_full_session_reports_invalid_state_over_ratio():
    """PRD §2.8: "The state-machine guard (priority six) runs after that: a resource
    that is not in a valid originating state for the requested transition fails with
    `ERR_INVALID_STATE` (409). The remaining business rules then apply in this order:
    instructor-ratio and seat-capacity enforcement (`ERR_RATIO_EXCEEDED`, 409), then
    per-enrollment session-overlap (`ERR_SESSION_OVERLAP`, 409)"

    A CLOSED session whose lone PRESENT seat keeps booked_seat_count at cap=1 trips both
    the state guard (booking is not valid from CLOSED) and the ratio rule; the earlier
    state guard wins -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/booking_invalid_state_beats_ratio_exceeded
    """
    center, subject, _level, family, _student, en1 = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    st2 = create_student(family["id"], full_name="K2", birthdate="2017-01-01T00:00:00Z")
    en2 = create_and_place_enrollment(center["id"], st2["id"], subject["id"])
    session = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                      "2026-05-01T10:00:00Z", 1)
    ar1 = book_seat(session["id"], en1["id"])
    validate_success(api.check_in_attendance(ar1["id"], INSTRUCTOR))
    set_clock("2026-05-01T09:30:00Z")
    validate_success(api.close_session(session["id"], DIRECTOR))

    closed = validate_success(api.get_session(session["id"], DIRECTOR))
    resp = api.create_attendance_record(
        {"session_id": session["id"], "enrollment_id": en2["id"],
         "expected_session_version": closed["version"]}, DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert closed["booked_seat_count"] == 1


def test_booking_closed_full_session_does_not_create_record():
    """PRD §2.8: "The state-machine guard (priority six) runs after that: a resource
    that is not in a valid originating state for the requested transition fails with
    `ERR_INVALID_STATE` (409)."
    PRD §3.5: "A director closes a session from `OPEN` to `CLOSED`"

    The rejected booking leaves the closed session's seat count unchanged; no
    AttendanceRecord for the second enrollment exists.

    Design: Difficulty/priority_pair_validation_conflict/booking_invalid_state_beats_ratio_exceeded
    """
    center, subject, _level, family, _student, en1 = setup_active_enrollment(
        clock="2026-05-01T08:00:00Z", instructor_ratio_cap=6)
    st2 = create_student(family["id"], full_name="K2", birthdate="2017-01-01T00:00:00Z")
    en2 = create_and_place_enrollment(center["id"], st2["id"], subject["id"])
    session = create_and_open_session(center["id"], "2026-05-01T09:00:00Z",
                                      "2026-05-01T10:00:00Z", 1)
    ar1 = book_seat(session["id"], en1["id"])
    validate_success(api.check_in_attendance(ar1["id"], INSTRUCTOR))
    set_clock("2026-05-01T09:30:00Z")
    validate_success(api.close_session(session["id"], DIRECTOR))
    closed = validate_success(api.get_session(session["id"], DIRECTOR))

    api.create_attendance_record(
        {"session_id": session["id"], "enrollment_id": en2["id"],
         "expected_session_version": closed["version"]}, DIRECTOR)
    records, _meta = _list(api.list_attendance_records(DIRECTOR, {"enrollment_id": en2["id"]}))
    assert records == [], "no AttendanceRecord created for the rejected booking"


def _list(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)


# ===========================================================================
# place_level_subject_mismatch_beats_invalid_request_ordering
# (well-formedness p4 ERR_INVALID_REQUEST pre-empts business p11)
# ===========================================================================
def test_worksheet_missing_field_and_wrong_subject_reports_invalid_request():
    """PRD §2.8: "Request well-formedness is checked fourth: required fields must be
    present, enum values must be legal, and numeric values must lie in their declared
    ranges ... a violation yields `ERR_INVALID_REQUEST` (422)"
    PRD §2.8: "then level-to-subject coherence (`ERR_LEVEL_SUBJECT_MISMATCH`, 409)"

    A worksheet create that BOTH omits the required `set_number` AND references a level
    from the wrong subject trips the earlier well-formedness gate (p4) -> ERR_INVALID_REQUEST.

    Design: Difficulty/priority_pair_validation_conflict/place_level_subject_mismatch_beats_invalid_request_ordering
    """
    center, _ag, subj_m, _lv = setup_operating_center_with_subject(num_levels=1)
    subj_r = create_subject(center["id"], name="READING", code="READ")
    r_lv1 = create_level(subj_r["id"], 1, label="R1", worksheets_to_master=2, mastery_score_threshold=80)
    family = create_family(center["id"])
    student = create_student(family["id"])
    en = create_and_place_enrollment(center["id"], student["id"], subj_m["id"])

    # Omit set_number (required) AND point level_id at the READING level (wrong subject).
    resp = api.create_worksheet(
        {"enrollment_id": en["id"], "level_id": r_lv1["id"]}, INSTRUCTOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_worksheet_invalid_request_creates_no_worksheet():
    """PRD §2.8: "Request well-formedness is checked fourth: required fields must be
    present ... a violation yields `ERR_INVALID_REQUEST` (422)"
    PRD §3.4: "Assigning one creates a `Worksheet` referencing the `enrollment_id` it
    belongs to, the `level_id` it targets, and a `set_number`"

    The rejected create produces no worksheet for the enrollment.

    Design: Difficulty/priority_pair_validation_conflict/place_level_subject_mismatch_beats_invalid_request_ordering
    """
    center, _ag, subj_m, _lv = setup_operating_center_with_subject(num_levels=1)
    subj_r = create_subject(center["id"], name="READING", code="READ")
    r_lv1 = create_level(subj_r["id"], 1, label="R1", worksheets_to_master=2, mastery_score_threshold=80)
    family = create_family(center["id"])
    student = create_student(family["id"])
    en = create_and_place_enrollment(center["id"], student["id"], subj_m["id"])

    api.create_worksheet({"enrollment_id": en["id"], "level_id": r_lv1["id"]}, INSTRUCTOR)
    records, _meta = _list(api.list_worksheets(DIRECTOR, {"enrollment_id": en["id"]}))
    assert records == [], "no Worksheet created for the malformed request"


# ===========================================================================
# mastery_threshold_ge_boundary_80_passes_79_retries
# ===========================================================================
def test_grade_at_threshold_exactly_masters():
    """PRD §3.4: "if the `score` is greater than or equal to the targeted level's
    `mastery_score_threshold`, the set advances from `GRADED` to `MASTERED`"

    Score exactly 80 (== threshold) -> MASTERED.

    Design: Difficulty/boundary_precision_check/mastery_threshold_ge_boundary_80_passes_79_retries
    """
    from test_helpers import setup_active_enrollment_with_worksheet
    *_rest, ws = setup_active_enrollment_with_worksheet(worksheets_to_master=2,
                                                        mastery_score_threshold=80)
    graded = validate_success(api.grade_worksheet(ws["id"], {"score": 80}, INSTRUCTOR))
    assert graded["status"] == "MASTERED", f"score 80 == threshold -> MASTERED, got {graded['status']}"


def test_grade_one_below_threshold_retries():
    """PRD §3.4: "otherwise it moves from `GRADED` to `RETRY`."
    PRD §3.4: "if the `score` is greater than or equal to the targeted level's
    `mastery_score_threshold`, the set advances from `GRADED` to `MASTERED`"

    Score 79 (threshold-1) is below 80 -> RETRY.

    Design: Difficulty/boundary_precision_check/mastery_threshold_ge_boundary_80_passes_79_retries
    """
    from test_helpers import setup_active_enrollment_with_worksheet
    *_rest, ws = setup_active_enrollment_with_worksheet(worksheets_to_master=2,
                                                        mastery_score_threshold=80)
    graded = validate_success(api.grade_worksheet(ws["id"], {"score": 79}, INSTRUCTOR))
    assert graded["status"] == "RETRY", f"score 79 < 80 -> RETRY, got {graded['status']}"


# ===========================================================================
# empty_invoice_zero_billable_components_rejected_on_issue
# ===========================================================================
def test_issue_invoice_with_zero_components_rejected():
    """PRD §3.7: "It may be issued only when there is something to bill — the sum of
    `tuition_component_cents` and `enrollment_fee_component_cents` is greater than 0 —
    otherwise it is rejected with `ERR_EMPTY_INVOICE`."

    A family whose only enrollment is still PLACEMENT_PENDING produces a draft invoice
    with zero billable components; issuing it -> ERR_EMPTY_INVOICE.

    Design: Difficulty/boundary_precision_check/empty_invoice_zero_billable_components_rejected_on_issue
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=15000, enrollment_fee_cents=5000)
    family = create_family(center["id"])
    student = create_student(family["id"])
    # Created but NOT placed -> still PLACEMENT_PENDING, not billable.
    create_enrollment(center["id"], student["id"], subject["id"], diagnostic_raw_score=10)
    inv = create_invoice(family["id"], center["id"], "2026-05")
    assert inv["tuition_component_cents"] == 0

    resp = api.issue_invoice(inv["id"], DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_EMPTY_INVOICE.value)


def test_empty_invoice_stays_draft_after_rejected_issue():
    """PRD §3.7: "Issuing an invoice moves it from `DRAFT` to `ISSUED` and pins the
    wallet and total. It may be issued only when there is something to bill ... otherwise
    it is rejected with `ERR_EMPTY_INVOICE`."

    The rejected issue leaves the invoice in DRAFT with zero tuition.

    Design: Difficulty/boundary_precision_check/empty_invoice_zero_billable_components_rejected_on_issue
    """
    center, _ag, subject, _levels = setup_operating_center_with_subject(
        num_levels=1, monthly_tuition_cents=15000, enrollment_fee_cents=5000)
    family = create_family(center["id"])
    student = create_student(family["id"])
    create_enrollment(center["id"], student["id"], subject["id"], diagnostic_raw_score=10)
    inv = create_invoice(family["id"], center["id"], "2026-05")

    api.issue_invoice(inv["id"], DIRECTOR)
    fresh = validate_success(api.get_invoice(inv["id"], DIRECTOR))
    assert fresh["status"] == "DRAFT"
    assert fresh["tuition_component_cents"] == 0
