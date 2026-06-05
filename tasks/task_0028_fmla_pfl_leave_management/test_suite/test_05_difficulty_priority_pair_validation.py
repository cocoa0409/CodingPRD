"""Difficulty Rule 5 — priority_pair_validation_conflict.

When two validation rules trigger for the same call, PRD §2.6's fixed precedence
determines which error_id is returned. State checks fire before
business_safety / business_constraint checks.
"""
from test_helpers import (
    ApiErrorId,
    approve_case_payload,
    TEST_USERS,
    create_employee,
    create_employer,
    evaluate_eligibility,
    set_clock,
    setup_case_in_eligibility_pending,
    submit_case,
    terminate_employee,
    validate_error,
)


class TestStateBeforeBusinessSafetyOnApprove:
    """PRD §2.6 explicit precedence: state (5) → ERR_INVALID_STATE wins over
    business_safety (7) → ERR_CERTIFICATION_INCOMPLETE.
    """

    def test_approve_on_eligibility_pending_returns_invalid_state_not_cert_incomplete(self, api):
        """PRD §2.6: "Validation is evaluated in a fixed total order, and the first failing check determines the response. The order is: (1) authentication header presence, returning `ERR_UNAUTHENTICATED`; (2) role authorization for the endpoint, returning `ERR_FORBIDDEN`; (3) path-id resolution left-to-right, returning `ERR_NOT_FOUND`; (4) request-body foreign-key resolution, returning `ERR_REFERENCED_ENTITY_NOT_FOUND`; (5) entity-state precondition for the requested transition, returning `ERR_INVALID_STATE`; (6) the acting employee is not in `TERMINATED` status for case submission, eligibility evaluation, and case approval, returning `ERR_EMPLOYEE_TERMINATED`; (7) on case approval, the most-recent `CertificationRecord` is `COMPLETE`, returning `ERR_CERTIFICATION_INCOMPLETE`"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
        """
        # Case is in ELIGIBILITY_PENDING — approval is not a permitted transition
        # from this state (state check #5 fires). No certification exists, so
        # business_safety #7 would also fire. PRD §2.6 mandates #5 wins.
        base = setup_case_in_eligibility_pending(
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
        )
        res = api.approve_case(
            base["case"]["id"],
            approve_case_payload(base["case"]["version"]),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestStateBeforeBusinessConstraintOnEvaluateEligibility:
    """PRD §2.6 explicit precedence: state-employee (6) → ERR_EMPLOYEE_TERMINATED
    wins over business_constraint (10) → ERR_INELIGIBLE.
    """

    def test_evaluate_eligibility_on_terminated_employee_with_low_hours_returns_terminated(self, api):
        """PRD §2.6: "(6) the acting employee is not in `TERMINATED` status for case submission, eligibility evaluation, and case approval, returning `ERR_EMPLOYEE_TERMINATED`; (7) on case approval, the most-recent `CertificationRecord` is `COMPLETE`, returning `ERR_CERTIFICATION_INCOMPLETE`; (8) on certification mark-complete for an `INTERMITTENT` or `REDUCED_SCHEDULE` case, the intermittent fields are populated, returning `ERR_INTERMITTENT_CERT_REQUIRED`; (9) the supplied optimistic-concurrency version field matches the live parent version on the two OCC-guarded endpoints, returning `ERR_STALE_VERSION`; (10) on eligibility evaluation, the employee meets both the twelve-months-of-service and the 1,250-hours thresholds, returning `ERR_INELIGIBLE`"
        PRD §3.3: "Once an acting employee's `employment_status` is `TERMINATED`, the three guarded calls — submitting a new case, evaluating eligibility on an existing case, and approving a case — all return `ERR_EMPLOYEE_TERMINATED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_on_evaluate_eligibility_terminated
        """
        # Employee has 1000 hours (would fail ineligible #10) AND is TERMINATED
        # (would fail #6). PRD §2.6 mandates #6 wins.
        employer = create_employer(state_code="FED")
        emp = create_employee(
            employer["id"],
            hire_date="2024-01-01T00:00:00.000Z",
            hours_worked_trailing_12mo=1000,  # ineligible
            home_state_code="FED",
        )
        set_clock("2026-05-01T00:00:00.000Z")
        case = submit_case(
            emp["id"],
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        terminate_employee(emp["id"])
        res = api.evaluate_eligibility(case["id"], TEST_USERS["hr_admin_headers"])
        validate_error(res, ApiErrorId.ERR_EMPLOYEE_TERMINATED)


class TestEligibleButTerminatedStillReturnsTerminated:
    """PRD §2.6 + §3.3: even when the eligibility thresholds would PASS, a
    TERMINATED employee blocks evaluate-eligibility with ERR_EMPLOYEE_TERMINATED.
    Confirms #6 wins regardless of #10's outcome.
    """

    def test_eligible_hours_2000_but_terminated_returns_employee_terminated(self, api):
        """PRD §3.3: "Once an acting employee's `employment_status` is `TERMINATED`, the three guarded calls — submitting a new case, evaluating eligibility on an existing case, and approving a case — all return `ERR_EMPLOYEE_TERMINATED`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_on_evaluate_eligibility_terminated
        """
        employer = create_employer(state_code="FED")
        emp = create_employee(
            employer["id"],
            hire_date="2024-01-01T00:00:00.000Z",
            hours_worked_trailing_12mo=2000,  # eligible
            home_state_code="FED",
        )
        set_clock("2026-05-01T00:00:00.000Z")
        case = submit_case(
            emp["id"],
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        terminate_employee(emp["id"])
        res = api.evaluate_eligibility(case["id"], TEST_USERS["hr_admin_headers"])
        validate_error(res, ApiErrorId.ERR_EMPLOYEE_TERMINATED)


class TestAuthBeforeStateOnTerminatedEmployeeApprove:
    """PRD §2.6 #1/#2 (auth) precede #5/#6 (state). Even with a terminated employee,
    a missing X-User-Role still returns ERR_UNAUTHENTICATED before any state check.
    """

    def test_missing_auth_header_beats_state_check_on_approve(self, api):
        """PRD §2.6: "the first failing check determines the response. The order is: (1) authentication header presence, returning `ERR_UNAUTHENTICATED`; (2) role authorization for the endpoint, returning `ERR_FORBIDDEN`"
        PRD §2.1: "A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
        """
        # Case is in ELIGIBILITY_PENDING (would fail #5 if auth headers were
        # present); but with no auth headers, auth #1 wins.
        base = setup_case_in_eligibility_pending(
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        res = api.approve_case(
            base["case"]["id"],
            approve_case_payload(base["case"]["version"]),
            headers={},  # no auth headers at all
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
