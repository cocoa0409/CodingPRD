"""Exam booking, scoring, prerequisites, retakes, and cascades (PRD §3.5)."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_student,
    create_default_package,
    book_exam,
    book_and_pass_exam,
    accumulate_training_hours,
    create_active_instructor,
    create_active_vehicle,
    record_result_payload,
    create_exam_payload,
    iso_z,
    future_window,
    _server_clock_now,
    ADMIN_HEADERS,
    make_examiner_headers,
    get_student,
)


class TestExamPrerequisites:

    def test_theory_stage_cannot_book_final_test(self, api):
        """PRD §3.5: "If the student's training_stage does not match the
        prerequisite, or if the exam is FINAL_TEST and has_passed_basic_practical
        is false, the booking is rejected with ERR_PREREQUISITE_STAGE_NOT_MET."

        # difficulty: cross_entity_state_dependency/exam_booking_requires_student_training_stage
        """
        student, _ = create_active_student(api)  # training_stage='THEORY'
        start, _, _ = future_window(api, offset_minutes=60, duration_minutes=60)
        resp = api.book_exam(create_exam_payload(student_id=student["id"],
                                                    exam_type="FINAL_TEST",
                                                    scheduled_at=start,
                                                    examiner_id="ex_01"),
                              ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_STAGE_NOT_MET.value)


class TestExamPassingScores:

    def test_theory_pass_advances_to_basic(self, api):
        """PRD §3.5: "If exam_type is THEORY_TEST, has_passed_theory becomes
        true and training_stage advances from THEORY to BASIC."
        """
        student, _ = create_active_student(api)
        exam = book_and_pass_exam(api, student=student, exam_type="THEORY_TEST", score=95)
        assert exam["status"] == "PASSED"
        s = get_student(api, student["id"])
        assert s["has_passed_theory"] is True
        assert s["training_stage"] == "BASIC"

    def test_score_below_passing_marks_failed(self, api):
        """PRD §3.5: "When score is strictly less than passing_score, the exam
        transitions from BOOKED to FAILED and no student-side cascade fires."
        """
        student, _ = create_active_student(api)
        exam = book_exam(api, student=student, exam_type="THEORY_TEST")
        # Score 89 < 90 (THEORY passing_score)
        resp = api.record_exam_result(exam["id"], record_result_payload(89),
                                       make_examiner_headers("ex_01"))
        data = validate_success(resp)
        assert data["status"] == "FAILED"
        s = get_student(api, student["id"])
        assert s["has_passed_theory"] is False
        assert s["training_stage"] == "THEORY"

    def test_passing_score_theory_is_90(self, api):
        """PRD §3.5: "THEORY_TEST requires at least 90"

        Claim: score=89 fails; score=90 passes. Exact boundary.
        """
        # 90 → PASSED
        student, _ = create_active_student(api)
        exam = book_exam(api, student=student, exam_type="THEORY_TEST")
        resp = api.record_exam_result(exam["id"], record_result_payload(90),
                                       make_examiner_headers("ex_01"))
        data = validate_success(resp)
        assert data["status"] == "PASSED"


class TestStageMinHours:
    """PRD §3.5: stage minimum hours check at exam booking time."""

    def test_basic_test_blocked_without_600_minutes(self, api):
        """PRD §3.5: "The required minutes for that stage are: 0 for THEORY,
        600 for BASIC, and 480 for HIGHWAY ... If the attested minutes are
        strictly less than the required minutes, the booking is rejected with
        ERR_STAGE_MIN_HOURS_NOT_MET."

        Claim: BASIC_TEST booking with 0 BASIC-stage validated minutes fails.
        """
        student, _ = create_active_student(api)
        # Pass theory to advance to BASIC
        book_and_pass_exam(api, student=student, exam_type="THEORY_TEST", score=95)

        # Try to book BASIC_TEST without any BASIC minutes
        start, _, _ = future_window(api, offset_minutes=24*60, duration_minutes=60)
        resp = api.book_exam(create_exam_payload(student_id=student["id"],
                                                    exam_type="BASIC_TEST",
                                                    scheduled_at=start,
                                                    examiner_id="ex_01"),
                              ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_STAGE_MIN_HOURS_NOT_MET.value)


class TestRetakeLimit:
    """PRD §3.5: retake_index ≤ 3."""

    def test_fourth_attempt_rejected(self, api):
        """PRD §3.5: "if assigning would exceed 3 (i.e., the proposed exam
        would be the 4th attempt at this exam_type), the booking is rejected
        with ERR_RETAKE_LIMIT_EXCEEDED."

        Claim: book three THEORY_TEST exams (each FAILED), then a 4th attempt
        is rejected.
        """
        student, _ = create_active_student(api)
        ex_headers = make_examiner_headers("ex_01")

        # Three failed attempts
        for _ in range(3):
            exam = book_exam(api, student=student, exam_type="THEORY_TEST")
            get_success_data(api.record_exam_result(exam["id"], record_result_payload(50), ex_headers))

        # 4th attempt rejected
        start, _, _ = future_window(api, offset_minutes=10*60, duration_minutes=60)
        resp = api.book_exam(create_exam_payload(student_id=student["id"],
                                                    exam_type="THEORY_TEST",
                                                    scheduled_at=start,
                                                    examiner_id="ex_01"),
                              ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_RETAKE_LIMIT_EXCEEDED.value)


class TestExamStateGate:

    def test_record_result_on_non_booked_rejected(self, api):
        """PRD §3.5: "If the exam is not in BOOKED, the request is rejected
        with ERR_EXAM_NOT_BOOKABLE."
        """
        student, _ = create_active_student(api)
        exam = book_and_pass_exam(api, student=student, exam_type="THEORY_TEST", score=95)
        # Now exam is PASSED — recording again rejected
        resp = api.record_exam_result(exam["id"], record_result_payload(95),
                                       make_examiner_headers("ex_01"))
        validate_error(resp, ApiErrorId.ERR_EXAM_NOT_BOOKABLE.value)


class TestFinalTestCascade:
    """Depth-4 cascade from FINAL_TEST PASS:
       Exam BOOKED→PASSED → Student.training_stage HIGHWAY→COMPLETED →
       Student.enrollment_status ACTIVE→COMPLETED →
       all PENDING TrainingHourRecord rows for this student → SUBMITTED with
       submitted_at=clock_now.

    PRD §3.5 + §3.1 (cascade narrative).
    # difficulty: transitive_cascade/final_test_pass_completion_cascade_depth4
    """

    def test_final_test_pass_cascades_to_submitted_records(self, api):
        """PRD §3.5: "If exam_type is FINAL_TEST, training_stage advances from
        HIGHWAY to COMPLETED and the student's enrollment_status cascades from
        ACTIVE to COMPLETED in the same operation, additionally bulk-submitting
        all PENDING TrainingHourRecord rows for this student to SUBMITTED."

        Claim: depth-4 cascade observed end to end.
        """
        package = create_default_package(api)  # total_minutes=2000
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        vehicle = create_active_vehicle(api)

        # Pass THEORY (→ stage=BASIC)
        book_and_pass_exam(api, student=student, exam_type="THEORY_TEST", score=95)

        # Accumulate 600 BASIC minutes (10 × 60-min)
        accumulate_training_hours(api, student=student, instructor=instructor, vehicle=vehicle,
                                    training_stage="BASIC", count=10,
                                    minutes_per_session=60, gps_distance_km=10.0)

        # Pass BASIC (→ stage=HIGHWAY)
        book_and_pass_exam(api, student=student, exam_type="BASIC_TEST", score=85)

        # Accumulate 480 HIGHWAY minutes (8 × 60-min)
        accumulate_training_hours(api, student=student, instructor=instructor, vehicle=vehicle,
                                    training_stage="HIGHWAY", count=8,
                                    minutes_per_session=60, gps_distance_km=10.0)

        # Confirm PENDING records
        hours = get_success_data(api.get_training_hours(student["id"], ADMIN_HEADERS))
        records_before = hours["records"]
        assert len(records_before) >= 18
        assert all(r["authority_submission_status"] == "PENDING" for r in records_before)

        # Pre-cascade: Student is ACTIVE at HIGHWAY
        s_before = get_student(api, student["id"])
        assert s_before["enrollment_status"] == "ACTIVE"
        assert s_before["training_stage"] == "HIGHWAY"

        # Book + record FINAL_TEST PASSED
        final_exam = book_and_pass_exam(api, student=student, exam_type="FINAL_TEST", score=90)
        assert final_exam["status"] == "PASSED"

        # Cascade observed
        s_after = get_student(api, student["id"])
        assert s_after["training_stage"] == "COMPLETED"
        assert s_after["enrollment_status"] == "COMPLETED"

        # All TrainingHourRecord SUBMITTED with submitted_at != null
        hours_after = get_success_data(api.get_training_hours(student["id"], ADMIN_HEADERS))
        for r in hours_after["records"]:
            assert r["authority_submission_status"] == "SUBMITTED"
            assert r["submitted_at"] is not None
