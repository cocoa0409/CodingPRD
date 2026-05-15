"""Check-in, exam-attempt submission, and evaluation survey (PRD §3.5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    create_check_in_payload,
    create_exam_attempt_payload,
    create_trainee,
    drive_session_to_in_progress,
    enroll_trainee,
    iso_utc,
    make_trainee_headers,
    setup_completed_enrollment,
    setup_open_session,
    submit_exam_attempt_payload,
    submit_exam_for_enrollment,
    validate_error,
    validate_success,
)


SESSION_START = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
SESSION_END = datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc)
ENROLL_DEADLINE = datetime(2026, 5, 31, 23, 0, tzinfo=timezone.utc)


# ===========================================================================
# Check-in channel coherence (PRD §3.5)
# ===========================================================================
class TestCheckInChannelCoherence:

    def test_ip_range_outside_allowed_cidrs_rejected(self, api):
        """PRD §3.5: "when the channel is IP_RANGE, the source_value
        must be an IPv4 dotted-quad falling inside either the
        10.0.0.0/8 range or the 192.168.0.0/16 range. A mismatch on
        any of these — an invalid QR token, an IP outside the allowed
        CIDR blocks, or an empty image reference — is rejected with
        ERR_CHECKIN_INVALID."

        Claim: IP_RANGE check-in with source_value=8.8.8.8 ->
        ERR_CHECKIN_INVALID.
        """
        env = setup_open_session(capacity=10, is_charged=False,
                                 start_at=SESSION_START, end_at=SESSION_END,
                                 enrollment_deadline=ENROLL_DEADLINE)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        # Drive to IN_PROGRESS so check-ins are accepted.
        drive_session_to_in_progress(env["session"]["id"], SESSION_START)
        payload = create_check_in_payload(
            enrollment_id=enrollment["id"],
            channel="IP_RANGE",
            source_value="8.8.8.8",
        )
        resp = api.create_check_in(env["session"]["id"], payload,
                                   make_trainee_headers(trainee["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKIN_INVALID.value)

    def test_face_channel_empty_source_rejected(self, api):
        """PRD §3.5: "when the channel is FACE, the source_value must
        be a non-empty image reference ... A mismatch on any of these
        — an invalid QR token, an IP outside the allowed CIDR blocks,
        or an empty image reference — is rejected with
        ERR_CHECKIN_INVALID."

        Claim: FACE channel + empty source_value -> ERR_CHECKIN_INVALID.
        """
        env = setup_open_session(capacity=10, is_charged=False,
                                 start_at=SESSION_START, end_at=SESSION_END,
                                 enrollment_deadline=ENROLL_DEADLINE)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        drive_session_to_in_progress(env["session"]["id"], SESSION_START)
        payload = create_check_in_payload(
            enrollment_id=enrollment["id"], channel="FACE", source_value="",
        )
        resp = api.create_check_in(env["session"]["id"], payload,
                                   make_trainee_headers(trainee["id"]))
        validate_error(resp, ApiErrorId.ERR_CHECKIN_INVALID.value)

    def test_ip_range_within_10_block_succeeds(self, api):
        """PRD §3.5: "when the channel is IP_RANGE, the source_value
        must be an IPv4 dotted-quad falling inside either the
        10.0.0.0/8 range or the 192.168.0.0/16 range."

        Claim: source_value=10.0.0.5 inside 10.0.0.0/8 is accepted.
        """
        env = setup_open_session(capacity=10, is_charged=False,
                                 start_at=SESSION_START, end_at=SESSION_END,
                                 enrollment_deadline=ENROLL_DEADLINE)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        drive_session_to_in_progress(env["session"]["id"], SESSION_START)
        payload = create_check_in_payload(
            enrollment_id=enrollment["id"],
            channel="IP_RANGE",
            source_value="10.0.0.5",
        )
        resp = api.create_check_in(env["session"]["id"], payload,
                                   make_trainee_headers(trainee["id"]))
        validate_success(resp, expected_status=201)


# ===========================================================================
# Exam: incomplete submission (PRD §3.5)
# ===========================================================================
class TestExamCompleteness:

    def test_missing_answer_rejected_with_incomplete_exam(self, api):
        """PRD §3.5: "The submission step accepts a single body field
        answers and requires that this payload include an answer for
        every question in questions — any missing answer returns
        ERR_INCOMPLETE_EXAM."

        Claim: submitting with fewer answers than questions ->
        ERR_INCOMPLETE_EXAM.
        """
        ctx = setup_completed_enrollment(
            attendance="PRESENT", exam_passed=True,
            with_certificate_template=False,
        )
        # The fixture has already submitted an exam — we cannot reuse
        # it. Instead, build a brand-new mini scenario: enroll a fresh
        # trainee for another session and submit answers omitting one
        # question.
        # Use a smaller approach: directly POST to /exam-attempts with
        # the existing enrollment's id is not allowed because the
        # session is already COMPLETED. Build a fresh open session.
        env = setup_open_session(capacity=10, is_charged=False,
                                 start_at=SESSION_START, end_at=SESSION_END,
                                 enrollment_deadline=ENROLL_DEADLINE)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        drive_session_to_in_progress(env["session"]["id"], SESSION_START)

        headers = make_trainee_headers(trainee["id"])
        attempt_resp = api.create_exam_attempt(
            create_exam_attempt_payload(enrollment_id=enrollment["id"]),
            headers,
        )
        attempt = validate_success(attempt_resp, expected_status=201)
        questions = attempt["questions"]
        assert len(questions) >= 1, "Exam attempt must contain at least one question"
        # Submit answers for ALL but the last question — if questions has only
        # one entry this yields an empty answers list, which still triggers
        # ERR_INCOMPLETE_EXAM per PRD §3.5.
        answers = [
            {"question_id": q["question_id"],
             "given_answer": q["correct_answer"]}
            for q in questions[:-1]
        ]
        resp = api.submit_exam_attempt(
            attempt["id"], submit_exam_attempt_payload(answers), headers,
        )
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_EXAM.value)


# ===========================================================================
# Exam scoring boundary and passed flag (PRD §3.5)
# ===========================================================================
class TestExamScoring:

    def test_perfect_answers_score_one_hundred_passed_true(self, api):
        """PRD §3.5: "The score is computed by summing the weight of
        every question whose given answer matches the correct answer,
        dividing that sum by total_weight, multiplying by one
        hundred, and rounding the final result half-up to two decimal
        places ... The passed flag is true when score is at or above
        70 and false otherwise."

        Claim: all-correct answers -> score=100.00, passed=true.
        """
        env = setup_open_session(capacity=10, is_charged=False,
                                 start_at=SESSION_START, end_at=SESSION_END,
                                 enrollment_deadline=ENROLL_DEADLINE)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        drive_session_to_in_progress(env["session"]["id"], SESSION_START)
        submitted = submit_exam_for_enrollment(enrollment, trainee, correctness=None)
        assert float(submitted["score"]) == 100.00
        assert submitted["passed"] is True

    def test_all_wrong_answers_score_zero_passed_false(self, api):
        """PRD §3.5: "the passed flag is true when score is at or
        above 70 and false otherwise."

        Claim: all-wrong answers -> score=0.00, passed=false.
        """
        env = setup_open_session(capacity=10, is_charged=False,
                                 start_at=SESSION_START, end_at=SESSION_END,
                                 enrollment_deadline=ENROLL_DEADLINE)
        trainee = create_trainee(job_level=5)
        enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
        drive_session_to_in_progress(env["session"]["id"], SESSION_START)
        # Build per-question correctness all False — submit_exam_for_enrollment
        # accepts a list shorter than questions and pads with False.
        submitted = submit_exam_for_enrollment(
            enrollment, trainee, correctness=[False] * 20,
        )
        assert float(submitted["score"]) == 0.00
        assert submitted["passed"] is False


# ===========================================================================
# Evaluation aggregate (PRD §3.5)
# ===========================================================================
class TestEvaluationAggregate:

    def test_aggregate_score_uses_weighted_sum(self, api):
        """PRD §3.5: "The aggregate_score is computed as the sum of
        content_score weighted at 0.4, instructor_score weighted at
        0.3, and logistics_score weighted at 0.3, rounded half-up to
        two decimal places."

        Claim: content=5, instructor=4, logistics=3 ->
        aggregate_score = round(5*0.4 + 4*0.3 + 3*0.3, 2) = 4.10.
        """
        ctx = setup_completed_enrollment(
            attendance="PRESENT", exam_passed=True,
            with_certificate_template=False,
        )
        trainee = ctx["trainee"]
        enrollment = ctx["enrollment"]
        from test_helpers import create_evaluation_payload
        payload = create_evaluation_payload(
            enrollment_id=enrollment["id"],
            content_score=5,
            instructor_score=4,
            logistics_score=3,
        )
        resp = api.create_evaluation(payload, make_trainee_headers(trainee["id"]))
        data = validate_success(resp, expected_status=201)
        # 5*0.4 + 4*0.3 + 3*0.3 = 2.0 + 1.2 + 0.9 = 4.10.
        assert float(data["aggregate_score"]) == pytest.approx(4.10, abs=0.01), (
            f"Expected aggregate_score == 4.10, got {data['aggregate_score']}"
        )

    def test_uniform_top_scores_aggregate_to_five(self, api):
        """PRD §3.5: "rounded half-up to two decimal places."

        Claim: content=5, instructor=5, logistics=5 ->
        aggregate_score = 5.00.
        """
        ctx = setup_completed_enrollment(
            attendance="PRESENT", exam_passed=True,
            with_certificate_template=False,
        )
        trainee = ctx["trainee"]
        enrollment = ctx["enrollment"]
        from test_helpers import create_evaluation_payload
        payload = create_evaluation_payload(
            enrollment_id=enrollment["id"],
            content_score=5,
            instructor_score=5,
            logistics_score=5,
        )
        resp = api.create_evaluation(payload, make_trainee_headers(trainee["id"]))
        data = validate_success(resp, expected_status=201)
        assert float(data["aggregate_score"]) == pytest.approx(5.00, abs=0.01)
