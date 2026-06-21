"""Difficulty Rule 7 — cross_entity_state_dependency.

A transition on one entity depends on the state of another: LeaveCase.approve
requires Employee.employment_status == ACTIVE; LeaveCase.approve requires
the most-recent CertificationRecord.certification_status == COMPLETE.
"""
from test_helpers import (
    ApiErrorId,
    approve_case_payload,
    get_case,
    setup_approved_case,
    setup_case_in_certification_pending,
    setup_case_with_received_insufficient_certification,
    submit_certification,
    TEST_USERS,
    terminate_employee,
    validate_error,
)


class TestApproveRequiresEmployeeActive:
    """PRD §3.3 + §3.4: approving a case requires Employee.employment_status to be
    not TERMINATED. The cross-entity dependency is LeaveCase ↔ Employee.
    """

    def test_approve_with_employee_terminated_after_cert_complete_returns_employee_terminated(self, api):
        """PRD §3.4: "The acting employee must not be `TERMINATED`."
        PRD §3.3: "Once an acting employee's `employment_status` is `TERMINATED`, the three guarded calls — submitting a new case, evaluating eligibility on an existing case, and approving a case — all return `ERR_EMPLOYEE_TERMINATED`."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_employee_not_terminated
        """
        # Build a case all the way through CERTIFICATION_PENDING with a COMPLETE cert,
        # then terminate the employee BEFORE approval. The certification COMPLETE
        # check would pass, but the employee-terminated check (#6) fires first.
        from test_helpers import (
            mark_certification_complete,
            receive_certification,
        )

        base = setup_case_in_certification_pending(
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        cert = submit_certification(
            base["case"]["id"],
            base["provider"]["id"],
            expected_duration_weeks=4,
            provider_attestation_signed_at="2026-05-15T00:00:00.000Z",
        )
        receive_certification(cert["id"])
        mark_certification_complete(cert["id"])
        terminate_employee(base["employee"]["id"])
        # Now attempt approve.
        res = api.approve_case(
            base["case"]["id"],
            approve_case_payload(base["case_version_post_eligibility"]),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_EMPLOYEE_TERMINATED)
        # And the case state remains CERTIFICATION_PENDING.
        case_after = get_case(base["case"]["id"])
        assert case_after["status"] == "CERTIFICATION_PENDING", (
            f"approve rejected by cross-entity precondition must NOT advance the case; "
            f"got {case_after['status']!r}"
        )

    def test_terminate_employee_on_leave_with_protection_is_rejected(self, api):
        """PRD §3.3: "if the employee is currently `ON_LEAVE` with `job_restoration_protected` still true, the termination attempt is rejected with `ERR_INVALID_STATE`, otherwise the status becomes `TERMINATED`."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_employee_not_terminated
        """
        # The reverse cross-entity guard: an Employee mutation is blocked by
        # related LeaveCase state. Approved + ACTIVE case with protection true
        # → terminate must be rejected.
        from test_helpers import record_interval, set_clock

        bundle = setup_approved_case(
            employer_state="FED",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-08T00:00:00.000Z",
            40,
        )
        # Employee is now ON_LEAVE with protection true.
        res = api.terminate_employee(
            bundle.employee["id"], TEST_USERS["hr_admin_headers"]
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestApproveRequiresCertificationComplete:
    """PRD §3.4: approving a case requires the most-recent CertificationRecord to be
    COMPLETE. Cross-entity dependency: LeaveCase ↔ CertificationRecord.
    """

    def test_approve_with_insufficient_cert_returns_cert_incomplete(self, api):
        """PRD §3.4: "The most-recent `CertificationRecord` on the case must be in `COMPLETE`; otherwise the approval is rejected with `ERR_CERTIFICATION_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_certification_complete
        """
        # Cert was received then marked insufficient → cert.status == INSUFFICIENT.
        # Approve must fail with ERR_CERTIFICATION_INCOMPLETE.
        base = setup_case_with_received_insufficient_certification(
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        res = api.approve_case(
            base["case"]["id"],
            approve_case_payload(base["case_version_post_eligibility"]),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CERTIFICATION_INCOMPLETE)
        case_after = get_case(base["case"]["id"])
        assert case_after["status"] == "CERTIFICATION_PENDING"

    def test_approve_with_pending_cert_returns_cert_incomplete(self, api):
        """PRD §3.4: "The most-recent `CertificationRecord` on the case must be in `COMPLETE`; otherwise the approval is rejected with `ERR_CERTIFICATION_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/approve_requires_certification_complete
        """
        # Cert submitted only; never received/completed → cert.status == PENDING.
        base = setup_case_in_certification_pending(
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        submit_certification(
            base["case"]["id"],
            base["provider"]["id"],
            expected_duration_weeks=4,
            provider_attestation_signed_at="2026-05-15T00:00:00.000Z",
        )
        res = api.approve_case(
            base["case"]["id"],
            approve_case_payload(base["case_version_post_eligibility"]),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(res, ApiErrorId.ERR_CERTIFICATION_INCOMPLETE)
