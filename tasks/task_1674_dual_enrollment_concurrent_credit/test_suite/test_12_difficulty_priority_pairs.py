"""Difficulty rule priority_pair_validation_conflict: when two validation rungs
fail on the same request, the PRD's fixed priority order decides which error
surfaces (PRD 2.10, 3.5)."""
from test_helpers import (
    ApiErrorId,
    confirm_enrollment,
    confirm_enrollment_raw,
    create_course,
    create_prerequisite,
    drop_enrollment,
    get_enrollment,
    get_offering,
    register_and_confirm,
    register_student,
    set_clock,
    setup_base,
    validate_error,
)

MATH_COURSE = {
    "course_code": "MATH151",
    "title": "College Algebra",
    "placement_exam_code": "MATH",
    "min_placement_score": 70,
}
MATH_PLACEMENT = {"exam_code": "MATH", "score": 85, "taken_at": "2026-08-01T00:00:00Z"}


def _add_unsatisfied_prerequisite(ctx):
    """Add MATH151 -> MATH099 (min C) after the fact; the student holds no POSTED
    COLLEGE MATH099 entry, so the priority-10 referential check would fail if the
    state check did not fire first."""
    prereq_course = create_course(
        course_code="MATH099", title="Pre-Algebra", college_credit_hours=2,
        hs_credit_units=0.5,
    )
    create_prerequisite(ctx["course"]["id"], prereq_course["id"], min_grade="C")


class TestConfirmStateVsReferentialPriority:
    def test_reconfirm_of_registered_enrollment_reports_state_not_prerequisite(self, api):
        """PRD 2.10: "Every endpoint applies its checks in a fixed priority order,
        so that when several rules are violated the same one always surfaces first."
        PRD 2.10: "State-machine preconditions and the OCC stale-version check are
        priority 6."
        PRD 2.10: "Business referential checks — terms open, term type and school
        match, prerequisites, placement, funding agreement, instructor
        credentialing — span priorities 9 through 14."
        PRD 3.5: "The request carries `expected_offering_version` per §2.8, and the
        checks run in this order: the enrollment is in `PENDING_VERIFICATION` (else
        `ERR_ENROLLMENT_INVALID_STATE`, HTTP 409); the offering's current `version`
        matches `expected_offering_version` (else `ERR_STALE_VERSION`, HTTP 412);
        the offering is `OPEN` (else `ERR_OFFERING_INVALID_STATE`); the student is
        `ELIGIBLE` and has `grade_level` at least 11 (else
        `ERR_STUDENT_NOT_ELIGIBLE`); the student's school is `ACTIVE` (else
        `ERR_SCHOOL_SUSPENDED`); the logical clock reads at or before the earlier
        of the two terms' `add_deadline` values (else `ERR_ADD_WINDOW_CLOSED`,
        HTTP 409); both terms are `OPEN` (else `ERR_TERM_NOT_OPEN`); every
        prerequisite of the offering's course is satisfied (else
        `ERR_PREREQUISITE_NOT_MET`, HTTP 409); placement requirements are met (else
        `ERR_PLACEMENT_MISSING` or `ERR_PLACEMENT_SCORE_INSUFFICIENT`, HTTP 409);
        and a `FundingAgreement` exists for the offering's `high_school_id` and
        `college_term_id` pair (else `ERR_NO_FUNDING_AGREEMENT`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_vs_referential_priority
        """
        ctx = setup_base(course_overrides=MATH_COURSE)
        pair = register_and_confirm(ctx, placement=MATH_PLACEMENT)
        assert pair["enrollment"]["status"] == "REGISTERED"
        _add_unsatisfied_prerequisite(ctx)

        response = confirm_enrollment_raw(ctx["offering"]["id"], pair["enrollment"]["id"])
        validate_error(response, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE.value)
        assert get_enrollment(pair["enrollment"]["id"])["status"] == "REGISTERED"

    def test_confirm_of_dropped_enrollment_reports_state_not_prerequisite(self, api):
        """PRD 2.10: "Every endpoint applies its checks in a fixed priority order,
        so that when several rules are violated the same one always surfaces first."
        PRD 2.10: "State-machine preconditions and the OCC stale-version check are
        priority 6."
        PRD 3.5: "The request carries `expected_offering_version` per §2.8, and the
        checks run in this order: the enrollment is in `PENDING_VERIFICATION` (else
        `ERR_ENROLLMENT_INVALID_STATE`, HTTP 409); the offering's current `version`
        matches `expected_offering_version` (else `ERR_STALE_VERSION`, HTTP 412);
        the offering is `OPEN` (else `ERR_OFFERING_INVALID_STATE`); the student is
        `ELIGIBLE` and has `grade_level` at least 11 (else
        `ERR_STUDENT_NOT_ELIGIBLE`); the student's school is `ACTIVE` (else
        `ERR_SCHOOL_SUSPENDED`); the logical clock reads at or before the earlier
        of the two terms' `add_deadline` values (else `ERR_ADD_WINDOW_CLOSED`,
        HTTP 409); both terms are `OPEN` (else `ERR_TERM_NOT_OPEN`); every
        prerequisite of the offering's course is satisfied (else
        `ERR_PREREQUISITE_NOT_MET`, HTTP 409); placement requirements are met (else
        `ERR_PLACEMENT_MISSING` or `ERR_PLACEMENT_SCORE_INSUFFICIENT`, HTTP 409);
        and a `FundingAgreement` exists for the offering's `high_school_id` and
        `college_term_id` pair (else `ERR_NO_FUNDING_AGREEMENT`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_vs_referential_priority
        """
        ctx = setup_base(course_overrides=MATH_COURSE)
        pair = register_and_confirm(ctx, placement=MATH_PLACEMENT)
        drop_enrollment(pair["enrollment"]["id"])
        assert get_enrollment(pair["enrollment"]["id"])["status"] == "DROPPED"
        _add_unsatisfied_prerequisite(ctx)

        response = confirm_enrollment_raw(ctx["offering"]["id"], pair["enrollment"]["id"])
        validate_error(response, ApiErrorId.ERR_ENROLLMENT_INVALID_STATE.value)


class TestConfirmTemporalVsReferentialPriority:
    def test_add_window_closed_masks_missing_funding_agreement(self, api):
        """PRD 2.10: "Every endpoint applies its checks in a fixed priority order,
        so that when several rules are violated the same one always surfaces first."
        PRD 2.10: "Business temporal checks — add/drop/withdraw windows, term-end
        for grading, term and articulation overlap — are priority 8."
        PRD 2.10: "Business referential checks — terms open, term type and school
        match, prerequisites, placement, funding agreement, instructor
        credentialing — span priorities 9 through 14."
        PRD 3.5: "The request carries `expected_offering_version` per §2.8, and the
        checks run in this order: the enrollment is in `PENDING_VERIFICATION` (else
        `ERR_ENROLLMENT_INVALID_STATE`, HTTP 409); the offering's current `version`
        matches `expected_offering_version` (else `ERR_STALE_VERSION`, HTTP 412);
        the offering is `OPEN` (else `ERR_OFFERING_INVALID_STATE`); the student is
        `ELIGIBLE` and has `grade_level` at least 11 (else
        `ERR_STUDENT_NOT_ELIGIBLE`); the student's school is `ACTIVE` (else
        `ERR_SCHOOL_SUSPENDED`); the logical clock reads at or before the earlier
        of the two terms' `add_deadline` values (else `ERR_ADD_WINDOW_CLOSED`,
        HTTP 409); both terms are `OPEN` (else `ERR_TERM_NOT_OPEN`); every
        prerequisite of the offering's course is satisfied (else
        `ERR_PREREQUISITE_NOT_MET`, HTTP 409); placement requirements are met (else
        `ERR_PLACEMENT_MISSING` or `ERR_PLACEMENT_SCORE_INSUFFICIENT`, HTTP 409);
        and a `FundingAgreement` exists for the offering's `high_school_id` and
        `college_term_id` pair (else `ERR_NO_FUNDING_AGREEMENT`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_vs_referential_priority
        """
        ctx = setup_base(funding=False)  # the referential failure
        pair = register_student(ctx)
        # Past min(college add 2026-09-01, HS add 2026-09-05) == 2026-09-01.
        set_clock("2026-09-02T00:00:00Z")

        response = confirm_enrollment_raw(ctx["offering"]["id"], pair["enrollment"]["id"])
        validate_error(response, ApiErrorId.ERR_ADD_WINDOW_CLOSED.value)
        assert get_enrollment(pair["enrollment"]["id"])["status"] == "PENDING_VERIFICATION"

    def test_add_window_closed_masks_missing_placement(self, api):
        """PRD 2.10: "Business temporal checks — add/drop/withdraw windows, term-end
        for grading, term and articulation overlap — are priority 8."
        PRD 3.5: "the logical clock reads at or before the earlier of the two
        terms' `add_deadline` values (else `ERR_ADD_WINDOW_CLOSED`, HTTP 409); both
        terms are `OPEN` (else `ERR_TERM_NOT_OPEN`); every prerequisite of the
        offering's course is satisfied (else `ERR_PREREQUISITE_NOT_MET`, HTTP 409);
        placement requirements are met (else `ERR_PLACEMENT_MISSING` or
        `ERR_PLACEMENT_SCORE_INSUFFICIENT`, HTTP 409); and a `FundingAgreement`
        exists for the offering's `high_school_id` and `college_term_id` pair (else
        `ERR_NO_FUNDING_AGREEMENT`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_temporal_vs_referential_priority
        """
        ctx = setup_base(course_overrides=MATH_COURSE)  # placement-gated course
        pair = register_student(ctx)  # no placement records: the referential failure
        set_clock("2026-09-02T00:00:00Z")  # past the effective add deadline

        response = confirm_enrollment_raw(ctx["offering"]["id"], pair["enrollment"]["id"])
        validate_error(response, ApiErrorId.ERR_ADD_WINDOW_CLOSED.value)
