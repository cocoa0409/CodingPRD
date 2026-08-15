"""The interview protocol: scheduling gates, half-open overlap, quota."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    complete_interview,
    create_interview_payload,
    make_threat_assessor_headers,
    schedule_interview,
    setup_case_under_assessment,
    validate_error,
    validate_success,
)

TA1 = make_threat_assessor_headers("ta_1")


class TestInterviewSchedulingBasics:
    def test_interview_body_case_fk_not_found_returns_404(self, api):
        """PRD: "Fourth, path identifiers are resolved left to right, and the
        first identifier that does not correspond to an existing resource
        produces a 404: `ERR_CASE_NOT_FOUND` when the missing resource is a
        threat case (whether referenced in the path or through a body
        `case_id`), `ERR_SCHOOL_NOT_FOUND` when a body `school_id` references
        a school that does not exist, `ERR_CONDITION_NOT_FOUND` when a
        `conditionIndex` path segment falls outside the referenced plan's
        `conditions` array, and `ERR_NOT_FOUND` for any other missing path
        resource."

        Design: Corner/validations/interview_body_case_fk_not_found_returns_404
        """
        resp = api.create_interview(
            create_interview_payload(NON_EXISTENT_UUID),
            TA1,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)

    def test_interview_rejects_inverted_time_range(self, api):
        """PRD: "The window must be non-degenerate: `ends_at` strictly later
        than `starts_at`, otherwise `ERR_INVALID_TIME_RANGE`."

        Design: Corner/endpoints/interview_rejects_inverted_time_range
        """
        case = setup_case_under_assessment()
        resp = api.create_interview(
            create_interview_payload(case["id"],
                                     starts_at="2026-08-05T10:00:00Z",
                                     ends_at="2026-08-05T10:00:00Z"),
            TA1,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)


class TestHalfOpenOverlap:
    def test_adjacent_interview_windows_are_allowed(self, api):
        """PRD: "Interviews for the same case may not overlap — the system
        treats each window as a half-open interval, so one interview ending at
        exactly the moment another begins is permitted, while any true
        intersection with an existing `SCHEDULED` interview for that case is
        rejected with `ERR_INTERVIEW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/interview_half_open_overlap_with_adjacency
        """
        case = setup_case_under_assessment()
        schedule_interview(case["id"], starts_at="2026-08-05T10:00:00Z",
                           ends_at="2026-08-05T11:00:00Z")

        resp = api.create_interview(
            create_interview_payload(case["id"],
                                     starts_at="2026-08-05T09:00:00Z",
                                     ends_at="2026-08-05T10:00:00Z"),
            TA1,
        )
        adjacent = validate_success(resp, 201)
        assert adjacent["status"] == "SCHEDULED", (
            "a window ending exactly at the existing start is permitted "
            "(half-open interval semantics)"
        )

    def test_overlapping_interview_window_is_rejected(self, api):
        """PRD: "Interviews for the same case may not overlap — the system
        treats each window as a half-open interval, so one interview ending at
        exactly the moment another begins is permitted, while any true
        intersection with an existing `SCHEDULED` interview for that case is
        rejected with `ERR_INTERVIEW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/interview_half_open_overlap_with_adjacency
        """
        case = setup_case_under_assessment()
        schedule_interview(case["id"], starts_at="2026-08-05T10:00:00Z",
                           ends_at="2026-08-05T11:00:00Z")

        resp = api.create_interview(
            create_interview_payload(case["id"],
                                     starts_at="2026-08-05T10:30:00Z",
                                     ends_at="2026-08-05T11:30:00Z"),
            TA1,
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_OVERLAP)


class TestInterviewQuota:
    def _schedule_eight_witness_interviews(self, case_id):
        for day in range(2, 10):
            schedule_interview(
                case_id,
                starts_at=f"2026-08-{day:02d}T10:00:00Z",
                ends_at=f"2026-08-{day:02d}T11:00:00Z",
            )

    def test_ninth_overlapping_interview_reports_quota_error(self, api):
        """PRD: "A case may carry at most eight interviews that are not
        `CANCELLED`; scheduling a ninth is rejected with
        `ERR_MAX_INTERVIEWS_EXCEEDED`."
        PRD: "Only then are state preconditions evaluated — the resource being
        acted upon and the case referenced in the body must each be in a state
        that permits the operation — and only after those come the
        business-safety rules (segregation of duties, interview gating,
        referral prerequisites, closure blockers, re-entry condition
        completeness), then uniqueness and quota constraints, then
        cadence-length limits, and finally temporal rules such as interval
        overlap and past-dated deadlines."

        Design: Difficulty/priority_pair_validation_conflict/interview_quota_error_beats_overlap
        """
        case = setup_case_under_assessment()
        self._schedule_eight_witness_interviews(case["id"])

        # The ninth interview both exceeds the eight-interview quota AND
        # overlaps the existing 2026-08-09T10:00-11:00 window.
        resp = api.create_interview(
            create_interview_payload(case["id"],
                                     starts_at="2026-08-09T10:30:00Z",
                                     ends_at="2026-08-09T11:30:00Z"),
            TA1,
        )
        validate_error(resp, ApiErrorId.ERR_MAX_INTERVIEWS_EXCEEDED)

    def test_ninth_non_overlapping_interview_reports_quota_error(self, api):
        """PRD: "A case may carry at most eight interviews that are not
        `CANCELLED`; scheduling a ninth is rejected with
        `ERR_MAX_INTERVIEWS_EXCEEDED`."
        PRD: "Only then are state preconditions evaluated — the resource being
        acted upon and the case referenced in the body must each be in a state
        that permits the operation — and only after those come the
        business-safety rules (segregation of duties, interview gating,
        referral prerequisites, closure blockers, re-entry condition
        completeness), then uniqueness and quota constraints, then
        cadence-length limits, and finally temporal rules such as interval
        overlap and past-dated deadlines."

        Design: Difficulty/priority_pair_validation_conflict/interview_quota_error_beats_overlap
        """
        case = setup_case_under_assessment()
        self._schedule_eight_witness_interviews(case["id"])

        # A ninth interview on a fresh day trips the quota alone.
        resp = api.create_interview(
            create_interview_payload(case["id"],
                                     starts_at="2026-08-10T10:00:00Z",
                                     ends_at="2026-08-10T11:00:00Z"),
            TA1,
        )
        validate_error(resp, ApiErrorId.ERR_MAX_INTERVIEWS_EXCEEDED)


class TestSubjectInterviewGate:
    def test_subject_interview_requires_completed_witness_first(self, api):
        """PRD: "And a `SUBJECT` interview may not be scheduled until at least
        one non-`SUBJECT` interview for the same case has reached `COMPLETED`;
        violating this sequencing is rejected with
        `ERR_SUBJECT_INTERVIEW_TOO_EARLY`."
        PRD: "Completing an interview — again `ThreatAssessor` work — requires
        it to still be `SCHEDULED` (`ERR_INTERVIEW_NOT_SCHEDULED` otherwise)
        and records the assessor's `findings_score`, an integer rating from 0
        to 10 inclusive, together with a non-empty `summary`; an out-of-range
        score or empty summary is `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/subject_interview_requires_completed_witness_first
        """
        case = setup_case_under_assessment()
        witness = schedule_interview(case["id"], interviewee_type="WITNESS",
                                     starts_at="2026-08-05T10:00:00Z",
                                     ends_at="2026-08-05T11:00:00Z")

        early_resp = api.create_interview(
            create_interview_payload(case["id"], interviewee_type="SUBJECT",
                                     starts_at="2026-08-06T10:00:00Z",
                                     ends_at="2026-08-06T11:00:00Z"),
            TA1,
        )
        validate_error(early_resp, ApiErrorId.ERR_SUBJECT_INTERVIEW_TOO_EARLY)

        completed = complete_interview(witness["id"], findings_score=6,
                                       summary="witness confirms statements")
        assert completed["status"] == "COMPLETED"
        assert completed["findings_score"] == 6

        later_resp = api.create_interview(
            create_interview_payload(case["id"], interviewee_type="SUBJECT",
                                     starts_at="2026-08-06T10:00:00Z",
                                     ends_at="2026-08-06T11:00:00Z"),
            TA1,
        )
        subject = validate_success(later_resp, 201)
        assert subject["status"] == "SCHEDULED"
        assert subject["interviewee_type"] == "SUBJECT"
