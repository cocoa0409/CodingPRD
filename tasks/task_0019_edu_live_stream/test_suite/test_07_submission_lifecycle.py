"""Assignment + submission cyclic loop, grading, plagiarism block (PRD §3.8)."""

import pytest

from test_helpers import (
    api_client,
    assert_submission,
    create_published_course,
    create_submission_payload,
    enroll_student,
    grade_submission,
    grade_submission_payload,
    make_instructor_headers,
    make_student_headers,
    publish_assignment,
    request_revision_payload,
    request_revision,
    resubmit,
    setup_submission_under_review,
    start_review,
    submit_assignment,
    update_submission_payload,
    validate_error,
    validate_success,
)


class TestSubmissionPayloadFormat:
    """PRD §3.8: 'When format is TEXT the body must contain payload_text and
    the other two payload fields must be null; when format is FILE the body
    must contain payload_file_url; when format is CODE the body must contain
    payload_code. A mismatch — wrong field set, missing field, or multiple
    payload fields populated simultaneously — is rejected with
    ERR_PAYLOAD_FORMAT_MISMATCH.'"""

    def test_text_assignment_with_file_payload_rejected(self, api):
        """PRD §3.8: 'A mismatch — wrong field set, missing field, or multiple
        payload fields populated simultaneously — is rejected with
        ERR_PAYLOAD_FORMAT_MISMATCH.'"""
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment = publish_assignment(course, instructor, fmt="TEXT")
        payload = create_submission_payload(enrollment["id"], fmt="TEXT")
        # Now mismatch: clear text and set file_url
        payload["payload_text"] = None
        payload["payload_file_url"] = "https://x.example/sub.pdf"
        res = api.create_submission(
            assignment["id"], payload, make_student_headers(student["id"])
        )
        validate_error(res, "ERR_PAYLOAD_FORMAT_MISMATCH")

    def test_text_assignment_with_multiple_payloads_rejected(self, api):
        """PRD §3.8: 'multiple payload fields populated simultaneously — is
        rejected with ERR_PAYLOAD_FORMAT_MISMATCH.'"""
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment = publish_assignment(course, instructor, fmt="TEXT")
        payload = create_submission_payload(enrollment["id"], fmt="TEXT")
        payload["payload_code"] = "print('x')"
        res = api.create_submission(
            assignment["id"], payload, make_student_headers(student["id"])
        )
        validate_error(res, "ERR_PAYLOAD_FORMAT_MISMATCH")

    def test_text_assignment_with_no_payload_rejected(self, api):
        """PRD §3.8: 'wrong field set, missing field ... is rejected with
        ERR_PAYLOAD_FORMAT_MISMATCH.'"""
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment = publish_assignment(course, instructor, fmt="TEXT")
        payload = {"enrollment_id": enrollment["id"], "payload_text": None,
                   "payload_file_url": None, "payload_code": None}
        res = api.create_submission(
            assignment["id"], payload, make_student_headers(student["id"])
        )
        validate_error(res, "ERR_PAYLOAD_FORMAT_MISMATCH")

    def test_text_assignment_with_text_payload_succeeds(self, api):
        """PRD §3.8 sanity: matching format produces SUBMITTED with revision_count=0."""
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment = publish_assignment(course, instructor, fmt="TEXT")
        sub = submit_assignment(assignment, enrollment, student, fmt="TEXT")
        assert_submission(sub)
        assert sub["status"] == "SUBMITTED"
        assert sub["revision_count"] == 0


class TestSubmissionPastDue:
    """PRD §3.8: 'The submission must arrive strictly before the assignment's
    due_ts; an attempt at or after the due time is rejected with
    ERR_SUBMISSION_PAST_DUE.'"""

    def test_submission_after_due_ts_rejected(self, api):
        """PRD §3.8: 'an attempt at or after the due time is rejected with
        ERR_SUBMISSION_PAST_DUE.'"""
        from test_helpers import advance_clock
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        # due in 100s
        advance_clock(0)
        assignment = publish_assignment(course, instructor, fmt="TEXT", due_ts=100)
        # Advance past due
        advance_clock(200)
        res = api.create_submission(
            assignment["id"],
            create_submission_payload(enrollment["id"], fmt="TEXT"),
            make_student_headers(student["id"]),
        )
        validate_error(res, "ERR_SUBMISSION_PAST_DUE")


class TestStartReviewAndCyclicLoop:
    """PRD §3.8: 'Either the course owner or the relevant teaching assistant
    ... may move a submission from SUBMITTED to UNDER_REVIEW ... the source
    state is required to be SUBMITTED (ERR_SUBMISSION_NOT_SUBMITTED).'"""

    def test_start_review_advances(self, api):
        """PRD §3.8: 'move a submission from SUBMITTED to UNDER_REVIEW.'"""
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment = publish_assignment(course, instructor, fmt="TEXT")
        sub = submit_assignment(assignment, enrollment, student, fmt="TEXT")
        res = api.start_submission_review(
            sub["id"], make_instructor_headers(instructor["id"])
        )
        out = validate_success(res, expected_status=200)
        assert out["status"] == "UNDER_REVIEW"

    def test_start_review_when_not_submitted_rejected(self, api):
        """PRD §3.8: 'the source state is required to be SUBMITTED
        (ERR_SUBMISSION_NOT_SUBMITTED).'"""
        course, instructor, _, _, _, sub = setup_submission_under_review()
        # sub is now UNDER_REVIEW
        res = api.start_submission_review(
            sub["id"], make_instructor_headers(instructor["id"])
        )
        validate_error(res, "ERR_SUBMISSION_NOT_SUBMITTED")

    def test_request_revision_increments_count_on_resubmit(self, api):
        """PRD §3.8: 'On success, revision_count increments by one' on the
        REVISION_REQUESTED → SUBMITTED leg.

        This test verifies that revision_count starts at 0, stays 0 through
        the request-revision step (which only goes UNDER_REVIEW →
        REVISION_REQUESTED), and increments to 1 only when the student
        resubmits.
        """
        course, instructor, student, enrollment, assignment, sub = setup_submission_under_review()
        sub2 = request_revision(sub, instructor, "please redo")
        assert sub2["status"] == "REVISION_REQUESTED"
        # PRD §3.8: revision_count increments on the resubmit leg.
        sub3 = resubmit(sub2, student, fmt="TEXT")
        assert sub3["status"] == "SUBMITTED"
        assert sub3["revision_count"] == 1, (
            f"revision_count must be 1 after first resubmit, got {sub3['revision_count']}"
        )

    def test_request_revision_missing_feedback_rejected(self, api):
        """PRD §3.8: 'a non-empty feedback body (ERR_FEEDBACK_REQUIRED).'"""
        course, instructor, _, _, _, sub = setup_submission_under_review()
        res = api.request_submission_revision(
            sub["id"], {"feedback": ""}, make_instructor_headers(instructor["id"])
        )
        validate_error(res, "ERR_FEEDBACK_REQUIRED")

    def test_revision_cap_reached_rejected(self, api):
        """PRD §3.8: 'a current revision_count strictly less than the revision
        cap of three (ERR_REVISION_CAP_REACHED — the cap is reached when
        revision_count equals three).'"""
        from test_helpers import reach_revision_count
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        # Drive submission until revision_count == 3
        assignment, sub = reach_revision_count(
            course, instructor, enrollment, student, target_count=3, fmt="TEXT"
        )
        # Now sub is in SUBMITTED with revision_count=3. Re-enter UNDER_REVIEW
        # and attempt to request another revision; this must be rejected.
        sub_ur = start_review(sub, instructor)
        res = api.request_submission_revision(
            sub_ur["id"],
            request_revision_payload("nope"),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_REVISION_CAP_REACHED")


class TestGrading:
    """PRD §3.8: 'Grading is restricted to the course owner ... is gated by
    four preconditions: the submission must still be UNDER_REVIEW
    (ERR_SUBMISSION_NOT_UNDER_REVIEW); the supplied score must lie within the
    closed range from zero to the assignment's max_score
    (ERR_SCORE_OUT_OF_RANGE); a non-empty feedback must be supplied
    (ERR_FEEDBACK_REQUIRED); and the plagiarism_score must be strictly less
    than the system's plagiarism block threshold unless the request body sets
    the override_plagiarism flag to true (ERR_PLAGIARISM_BLOCKED).'"""

    def test_grade_advances_to_graded(self, api):
        """PRD §3.8: 'the terminal grade transition.'"""
        course, instructor, _, _, _, sub = setup_submission_under_review()
        res = api.grade_submission(
            sub["id"],
            grade_submission_payload(score=80, feedback="ok"),
            make_instructor_headers(instructor["id"]),
        )
        graded = validate_success(res, expected_status=200)
        assert graded["status"] == "GRADED"

    def test_grade_score_out_of_range_high_rejected(self, api):
        """PRD §3.8: 'the supplied score must lie within the closed range from
        zero to the assignment's max_score (ERR_SCORE_OUT_OF_RANGE).'"""
        course, instructor, _, _, _, sub = setup_submission_under_review(max_score=100)
        res = api.grade_submission(
            sub["id"],
            grade_submission_payload(score=101, feedback="ok"),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_SCORE_OUT_OF_RANGE")

    def test_grade_score_out_of_range_negative_rejected(self, api):
        """PRD §3.8: 'the supplied score must lie within the closed range from
        zero to the assignment's max_score (ERR_SCORE_OUT_OF_RANGE).'"""
        course, instructor, _, _, _, sub = setup_submission_under_review(max_score=100)
        res = api.grade_submission(
            sub["id"],
            grade_submission_payload(score=-1, feedback="ok"),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_SCORE_OUT_OF_RANGE")

    def test_grade_score_exactly_max_score_accepted(self, api):
        """PRD §3.8: 'the closed range from zero to the assignment's max_score'
        — the upper bound max_score is inclusive."""
        course, instructor, _, _, _, sub = setup_submission_under_review(max_score=100)
        res = api.grade_submission(
            sub["id"],
            grade_submission_payload(score=100, feedback="ok"),
            make_instructor_headers(instructor["id"]),
        )
        validate_success(res, expected_status=200)

    def test_grade_missing_feedback_rejected(self, api):
        """PRD §3.8: 'a non-empty feedback must be supplied
        (ERR_FEEDBACK_REQUIRED).'"""
        course, instructor, _, _, _, sub = setup_submission_under_review()
        res = api.grade_submission(
            sub["id"],
            {"score": 80, "feedback": ""},
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_FEEDBACK_REQUIRED")

    def test_grade_when_not_under_review_rejected(self, api):
        """PRD §3.8: 'the submission must still be UNDER_REVIEW
        (ERR_SUBMISSION_NOT_UNDER_REVIEW).'"""
        course, instructor, _ = create_published_course()
        enrollment, student = enroll_student(course)
        assignment = publish_assignment(course, instructor, fmt="TEXT")
        sub = submit_assignment(assignment, enrollment, student, fmt="TEXT")
        # sub is SUBMITTED, not UNDER_REVIEW.
        res = api.grade_submission(
            sub["id"],
            grade_submission_payload(score=80, feedback="ok"),
            make_instructor_headers(instructor["id"]),
        )
        validate_error(res, "ERR_SUBMISSION_NOT_UNDER_REVIEW")
