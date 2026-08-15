"""Pass-rate surveillance and the approval renewal cycles (PRD §3.1, §3.2, §3.3).

Covers first-attempt vs all-attempts pass-rate variants, the strict-below
probation boundary, probation gating of regulatory operations, and the cyclic
approval renewal loop.
"""
from test_helpers import (
    ApiErrorId,
    approve_course,
    assert_course_approval,
    create_active_course,
    create_credentialed_instructor,
    create_grant,
    create_licensed_school,
    create_offering,
    create_published_offering,
    create_proctor,
    create_student,
    enroll_with_seat_time,
    get_grant,
    get_school,
    get_success_data,
    run_sweep,
    score_attempt_proctored,
    set_clock,
    setup_publishable_school,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import COMPLIANCE, DIRECTOR, REGISTRAR, COMMISSION
from test_helpers import api_client


def _ten_scored_first_attempts(api, env, proctor_id, fail_scores, pass_scores,
                               retake_scores=None):
    """Drive N students through SEAT_TIME_MET and score their first attempts.

    fail_scores/pass_scores: lists of score_pct for first attempts.
    retake_scores: optional list of (enrollment_index, score) retakes.
    Returns list of enrollment dicts (in order).
    """
    enrollments = []
    for score in list(fail_scores) + list(pass_scores):
        _s, enr = enroll_with_seat_time(env["offering"]["id"], env["school"]["id"],
                                        env["instructor"]["id"], minutes=60)
        score_attempt_proctored(enr["id"], env["instructor"]["id"], proctor_id, score,
                                scheduled_at="2026-09-11T14:00:00Z")
        enrollments.append(enr)
    for idx, score in (retake_scores or []):
        score_attempt_proctored(enrollments[idx]["id"], env["instructor"]["id"],
                                proctor_id, score,
                                scheduled_at="2026-09-12T14:00:00Z")
    return enrollments


# ---------------------------------------------------------------------------
# Difficulty/dual_variant_calc/pass_rate_first_attempt_vs_all_attempts
# ---------------------------------------------------------------------------

class TestPassRateFirstAttemptVsAllAttempts:
    def test_summary_reports_both_variants(self, api):
        """PRD §3.1: "The school's `first_attempt_pass_rate_bps` is the count of
        `PASSED` outcomes in that set multiplied by 10000 and divided by the
        set's size, rounded half-up to an integer... A parallel
        `all_attempts_pass_rate_bps` is computed identically over all scored
        attempts in the window, retakes included."

        Design: Difficulty/dual_variant_calc/pass_rate_first_attempt_vs_all_attempts
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60},
                                       offering_overrides={"capacity": 20})
        proctor = create_proctor(env["school"]["id"])
        # 5 first-attempt fails (60), 5 first-attempt passes (90).
        enrollments = _ten_scored_first_attempts(
            api, env, proctor["id"],
            fail_scores=[60, 60, 60, 60, 60], pass_scores=[90, 90, 90, 90, 90],
            retake_scores=[(0, 90), (1, 90), (2, 90), (3, 90), (4, 50)])
        summary = get_success_data(api.get_pass_rate_summary(env["school"]["id"], COMPLIANCE))
        assert summary["first_attempt_count"] == 10
        assert summary["first_attempt_pass_rate_bps"] == 5000   # 5/10
        assert summary["all_attempt_count"] == 15
        assert summary["all_attempts_pass_rate_bps"] == 6000    # 9/15 incl. retakes
        return env, enrollments

    def test_probation_keys_on_first_attempt_variant_only(self, api):
        """PRD §3.1: "Posture changes only when the first-attempt set holds at
        least 10 entries: below the floor — strictly below; a rate exactly equal
        to `pass_rate_threshold_bps` does not trigger probation — the school's
        `posture` becomes `PROBATION`". Here 5/10 first attempts = 5000 bps <
        6000 floor even though the all-attempts rate sits at the floor.

        Design: Difficulty/dual_variant_calc/pass_rate_first_attempt_vs_all_attempts
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60},
                                       offering_overrides={"capacity": 20})
        proctor = create_proctor(env["school"]["id"])
        enrollments = _ten_scored_first_attempts(
            api, env, proctor["id"],
            fail_scores=[60, 60, 60, 60, 60], pass_scores=[90, 90, 90, 90, 90],
            retake_scores=[(0, 90), (1, 90), (2, 90), (3, 90), (4, 50)])
        run_sweep()
        school = get_school(env["school"]["id"])
        assert school["posture"] == "PROBATION", "keys on the FIRST_ATTEMPT variant only"
        assert school["last_evaluation_first_attempt_pass_rate_bps"] == 5000
        assert school["last_evaluation_attempt_count"] == 10
        # Second FAIL at attempts_used == max_exam_attempts (2) -> FAILED.
        fifth = get_success_data(api.get_enrollment(enrollments[4]["id"], REGISTRAR))
        assert fifth["academic_status"] == "FAILED"


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/pass_rate_exactly_at_threshold_stays_good_standing
# ---------------------------------------------------------------------------

class TestPassRateExactlyAtThreshold:
    def test_summary_at_threshold(self, api):
        """PRD §3.1: "The school's `first_attempt_pass_rate_bps` is the count of
        `PASSED` outcomes in that set multiplied by 10000 and divided by the
        set's size, rounded half-up to an integer". 6/10 first attempts = 6000
        bps == the default floor.

        Design: Difficulty/boundary_precision_check/pass_rate_exactly_at_threshold_stays_good_standing
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60},
                                       offering_overrides={"capacity": 20})
        proctor = create_proctor(env["school"]["id"])
        _ten_scored_first_attempts(api, env, proctor["id"],
                                   fail_scores=[60, 60, 60, 60],
                                   pass_scores=[90, 90, 90, 90, 90, 90])
        summary = get_success_data(api.get_pass_rate_summary(env["school"]["id"], COMPLIANCE))
        assert summary["first_attempt_count"] == 10
        assert summary["first_attempt_pass_rate_bps"] == 6000

    def test_equality_does_not_trigger_probation(self, api):
        """PRD §3.1: "Posture changes only when the first-attempt set holds at
        least 10 entries: below the floor — strictly below; a rate exactly equal
        to `pass_rate_threshold_bps` does not trigger probation — the school's
        `posture` becomes `PROBATION`, and at or above the floor it becomes
        `GOOD_STANDING`."

        Design: Difficulty/boundary_precision_check/pass_rate_exactly_at_threshold_stays_good_standing
        """
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60},
                                       offering_overrides={"capacity": 20})
        proctor = create_proctor(env["school"]["id"])
        _ten_scored_first_attempts(api, env, proctor["id"],
                                   fail_scores=[60, 60, 60, 60],
                                   pass_scores=[90, 90, 90, 90, 90, 90])
        run_sweep()
        school = get_school(env["school"]["id"])
        assert school["posture"] == "GOOD_STANDING", "strict '<' — equality spares probation"
        assert school["last_evaluation_first_attempt_pass_rate_bps"] == 6000


# ---------------------------------------------------------------------------
# Corner/validations/cn_probation_gates_regulatory_operations
# ---------------------------------------------------------------------------

class TestProbationGatesRegulatoryOperations:
    def _probation_school(self, api):
        env = setup_publishable_school(course_overrides={"required_seat_minutes": 60},
                                       offering_overrides={"capacity": 20})
        proctor = create_proctor(env["school"]["id"])
        _ten_scored_first_attempts(api, env, proctor["id"],
                                   fail_scores=[60, 60, 60, 60, 60],
                                   pass_scores=[90, 90, 90, 90, 90])
        run_sweep()
        return env

    def test_approval_submission_blocked_on_probation(self, api):
        """PRD §3.1: "A probation reading guards the regulatory surface: while
        `posture` is `PROBATION`, new course-approval applications, approval
        renewals, and offering publication are rejected with
        `ERR_SCHOOL_ON_PROBATION`."

        Design: Corner/validations/cn_probation_gates_regulatory_operations
        """
        env = self._probation_school(api)
        school = get_school(env["school"]["id"])
        assert school["posture"] == "PROBATION"
        assert school["status"] == "LICENSED", "posture is orthogonal to lifecycle"
        new_course = get_success_data(api.create_course(
            {"school_id": env["school"]["id"], "course_code": "CE-NEW",
             "title": "New CE", "course_type": "CONTINUING_ED",
             "required_seat_minutes": 60, "tuition_cents": 10000,
             "pass_score_pct": 70, "completion_deadline_days": 30,
             "ce_credit_hours": 3.0}, DIRECTOR))
        resp = api.create_course_approval(new_course["id"], {"state_code": "TX"}, COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_SCHOOL_ON_PROBATION)

    def test_offering_publish_blocked_on_probation(self, api):
        """PRD §3.1: "A probation reading guards the regulatory surface: while
        `posture` is `PROBATION`, new course-approval applications, approval
        renewals, and offering publication are rejected with
        `ERR_SCHOOL_ON_PROBATION`."

        Design: Corner/validations/cn_probation_gates_regulatory_operations
        """
        env = self._probation_school(api)
        new_offering = create_offering(
            env["course"]["id"], env["instructor"]["id"],
            start_date="2026-10-01", end_date="2026-10-05", capacity=5)
        resp = api.publish_offering(new_offering["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_SCHOOL_ON_PROBATION)


# ---------------------------------------------------------------------------
# Difficulty/non_linear_state_machine/course_approval_renewal_cycle
# ---------------------------------------------------------------------------

class TestCourseApprovalRenewalCycle:
    def _approval_in_expiring(self, api):
        """Course approval APPROVED with valid_until 2026-09-30; clock at
        2026-09-01 and swept once -> EXPIRING."""
        school = create_licensed_school()
        from test_helpers.fixtures import create_course
        course = create_course(school["id"])
        approval = approve_course(course["id"], valid_until="2026-09-30")
        set_clock("2026-09-01T00:00:00Z")
        run_sweep()
        data, _meta = validate_paginated(api.list_course_approvals(course["id"], COMPLIANCE))
        assert data[0]["status"] == "EXPIRING", "today within 30 days of valid_until"
        return school, course, approval

    def test_renewal_closes_the_loop_and_increments_round(self, api):
        """PRD §3.2: "Approving a renewal increments `application_round` by 1,
        stamps the new validity window, and returns the application to
        `APPROVED`".

        Design: Difficulty/non_linear_state_machine/course_approval_renewal_cycle
        """
        _school, _course, approval = self._approval_in_expiring(api)
        renewed = get_success_data(api.renew_approval(approval["id"], COMPLIANCE))
        assert renewed["status"] == "RENEWAL_PENDING"
        decided = get_success_data(api.decide_approval(
            approval["id"],
            {"decision": "APPROVED", "valid_from": "2026-10-01",
             "valid_until": "2027-09-30"},
            COMMISSION))
        assert_course_approval(decided)
        assert decided["status"] == "APPROVED", "full renewal cycle closed"
        assert decided["application_round"] == 2, "renewal approval increments the round"
        assert decided["valid_until"] == "2027-09-30"

    def test_expiring_transition_fires_in_thirty_day_runway(self, api):
        """PRD §3.2: "An `APPROVED` application whose `valid_until` is 30 or
        fewer days away (and not yet passed) moves to `EXPIRING`".

        Design: Difficulty/non_linear_state_machine/course_approval_renewal_cycle
        """
        school = create_licensed_school()
        from test_helpers.fixtures import create_course
        course = create_course(school["id"])
        approval = approve_course(course["id"], valid_until="2026-09-30")
        # Before the runway: no EXPIRING.
        set_clock("2026-08-15T00:00:00Z")
        run_sweep()
        data, _meta = validate_paginated(api.list_course_approvals(course["id"], COMPLIANCE))
        assert data[0]["status"] == "APPROVED", "46 days out is outside the 30-day runway"
        # Inside the runway: EXPIRING.
        set_clock("2026-09-01T00:00:00Z")
        run_sweep()
        data, _meta = validate_paginated(api.list_course_approvals(course["id"], COMPLIANCE))
        assert data[0]["status"] == "EXPIRING"
