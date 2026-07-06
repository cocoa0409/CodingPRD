"""Autopsy scheduling: temporal overlap and due-time boundary."""
from test_helpers import (
    validate_success, validate_error,
    create_investigator, create_pathologist,
    set_clock, create_investigating_case,
    schedule_autopsy,
    make_pathologist_headers,
    create_autopsy_exam_payload,
    complete_autopsy_exam_payload,
)


def test_pathologist_double_booked_half_open_overlap(api):
    """PRD §3.4: "The reserved window is the half-open interval running from scheduled_for up
    to (but not including) scheduled_for plus duration_minutes. A new exam whose interval
    overlaps any existing SCHEDULED exam for the same pathologist_user_id is rejected with
    ERR_PATHOLOGIST_DOUBLE_BOOKED (HTTP 409); two exams that merely touch — one ending exactly
    when the next begins — are adjacent, not overlapping, and are allowed."

    Design: Difficulty/resource_temporal_overlap/pathologist_double_booked_half_open_overlap
    """
    set_clock("2026-05-08T00:00:00Z")
    inv = create_investigator("Inv O")
    path = create_pathologist("Path O")
    case1, body1 = create_investigating_case(inv, case_type="NATURAL")
    # First exam 00:00-01:00.
    schedule_autopsy(path, case1, "2026-05-10T00:00:00Z", 60)

    case2, body2 = create_investigating_case(inv, case_type="NATURAL")
    path_headers = make_pathologist_headers(path["id"])
    # Second exam 00:30-01:30 overlaps the first.
    res = api.create_autopsy_exam(
        case2["id"],
        create_autopsy_exam_payload(path["id"], "2026-05-10T00:30:00Z", 60),
        path_headers,
    )
    validate_error(res, "ERR_PATHOLOGIST_DOUBLE_BOOKED", expected_status=409)


def test_complete_before_scheduled_instant_rejected(api):
    """PRD §3.4: "An autopsy may be completed only once the logical clock has reached or passed
    its scheduled_for instant — an attempt before that time is rejected with ERR_EXAM_NOT_DUE
    (HTTP 409) — and only by the very pathologist recorded on the exam, whose acting identity
    must equal the exam's pathologist_user_id."

    Design: Difficulty/boundary_precision_check/exam_not_due_at_scheduled_instant_boundary
    """
    set_clock("2026-05-08T00:00:00Z")
    inv = create_investigator("Inv L")
    path = create_pathologist("Path L")
    case, body = create_investigating_case(inv, case_type="NATURAL")
    exam = schedule_autopsy(path, case, "2026-05-10T00:00:00Z", 60)

    # One second before scheduled_for.
    set_clock("2026-05-09T23:59:59Z")
    path_headers = make_pathologist_headers(path["id"])
    res = api.complete_autopsy_exam(
        exam["id"], complete_autopsy_exam_payload("x", "y"), path_headers
    )
    validate_error(res, "ERR_EXAM_NOT_DUE", expected_status=409)


def test_cancelled_exam_cannot_complete(api):
    """PRD §3.4: "Alternatively a scheduled exam may be cancelled, moving it SCHEDULED ->
    CANCELLED and releasing the reserved schedule interval so the pathologist's calendar frees
    up." PRD §2.12: "state-machine legality (ERR_INVALID_STATE)".

    Design: Corner/state_machines/cancelled_exam_cannot_complete
    """
    inv = create_investigator("Inv CS4")
    path = create_pathologist("Path CS4")
    case, body = create_investigating_case(inv, case_type="NATURAL")
    exam = schedule_autopsy(path, case, "2026-05-01T00:00:00Z", 60)

    path_headers = make_pathologist_headers(path["id"])
    validate_success(api.cancel_autopsy_exam(exam["id"], path_headers), 200)
    res = api.complete_autopsy_exam(
        exam["id"], complete_autopsy_exam_payload("x", "y"), path_headers
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
