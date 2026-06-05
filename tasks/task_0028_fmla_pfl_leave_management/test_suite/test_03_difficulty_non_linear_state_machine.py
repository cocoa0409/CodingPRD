"""Difficulty Rule 3 — non_linear_state_machine.

Branching transition on LeaveCase (eligibility evaluation → CERTIFICATION_PENDING
or DENIED), and the certification cycle (a COMPLETE certification can be reopened
to RECERTIFICATION_REQUESTED while a new PENDING record walks its own path).
"""
from test_helpers import (
    ApiErrorId,
    approve_case_payload,
    create_employee,
    create_employer,
    evaluate_eligibility,
    get_case,
    get_certification,
    mark_certification_complete,
    receive_certification,
    request_recertification,
    set_clock,
    setup_approved_case,
    submit_case,
    submit_certification,
    TEST_USERS,
    validate_error,
)


class TestLeaveCaseBranchingEligibilityEvaluation:
    """PRD §3.3: same trigger (evaluate-eligibility) branches to
    CERTIFICATION_PENDING when both thresholds pass, or to DENIED when either
    fails — two divergent terminal/non-terminal outcomes.
    """

    def test_eligible_case_advances_to_certification_pending(self, api):
        """PRD §3.3: "The case advances to `CERTIFICATION_PENDING` only when both thresholds hold; otherwise the case is moved straight to `DENIED`."
        PRD §3.3: "Either outcome stamps `eligibility_evaluated` to true, snapshots the tenure as `tenure_months_at_request` (the floored months value), and snapshots the running hours figure as `hours_at_request`."

        Design: Difficulty/non_linear_state_machine/leave_case_branching_eligibility_pending_to_denied_vs_certpending
        """
        employer = create_employer(state_code="FED")
        eligible_emp = create_employee(
            employer["id"],
            email="e1@x.com",
            hire_date="2024-01-01T00:00:00.000Z",
            hours_worked_trailing_12mo=2000,
            home_state_code="FED",
        )
        set_clock("2026-05-01T00:00:00.000Z")
        case = submit_case(
            eligible_emp["id"],
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        case_after = evaluate_eligibility(case["id"])
        assert case_after["status"] == "CERTIFICATION_PENDING", (
            f"Eligible employee → CERTIFICATION_PENDING; got {case_after['status']!r}"
        )
        assert case_after["eligibility_evaluated"] is True

    def test_ineligible_hours_branches_to_denied_and_blocks_further_transitions(self, api):
        """PRD §3.3: "The case advances to `CERTIFICATION_PENDING` only when both thresholds hold; otherwise the case is moved straight to `DENIED`."
        PRD §3.6: "`LeaveCase.status` ranges over `SUBMITTED`, `ELIGIBILITY_PENDING`, `CERTIFICATION_PENDING`, `APPROVED`, `DENIED`, `ACTIVE`, `COMPLETED`, `JOB_RESTORED`, and `JOB_FORFEITED`; `DENIED`, `JOB_RESTORED`, and `JOB_FORFEITED` are terminal."

        Design: Difficulty/non_linear_state_machine/leave_case_branching_eligibility_pending_to_denied_vs_certpending
        """
        employer = create_employer(state_code="FED")
        ineligible_emp = create_employee(
            employer["id"],
            email="e2@x.com",
            hire_date="2024-01-01T00:00:00.000Z",
            hours_worked_trailing_12mo=1000,
            home_state_code="FED",
        )
        set_clock("2026-05-01T00:00:00.000Z")
        case = submit_case(
            ineligible_emp["id"],
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        # PRD §3.3: "The threshold-failure branch returns `ERR_INELIGIBLE` to the
        # caller when the call was driven against an employee who fails one or
        # both checks at the moment of evaluation." The error response is what
        # the API returns; the case state is mutated as a side effect and must
        # be observed via a follow-up GET (PRD §3.3 also: "Either outcome stamps
        # `eligibility_evaluated` to true ... otherwise the case is moved straight
        # to `DENIED`").
        elig_res = api.evaluate_eligibility(case["id"], TEST_USERS["hr_admin_headers"])
        validate_error(elig_res, ApiErrorId.ERR_INELIGIBLE)
        case_after = get_case(case["id"])
        assert case_after["status"] == "DENIED", (
            f"Ineligible (1000 < 1250 hours) → DENIED; got {case_after['status']!r}"
        )
        assert case_after["eligibility_evaluated"] is True
        # DENIED is terminal: a follow-up approve must fail with ERR_INVALID_STATE.
        approve_res = api.approve_case(
            case_after["id"],
            approve_case_payload(case_after["version"]),
            TEST_USERS["hr_admin_headers"],
        )
        validate_error(approve_res, ApiErrorId.ERR_INVALID_STATE)


class TestCertificationCycleCompleteToRecertThenBackToComplete:
    """PRD §3.5: a COMPLETE record on an APPROVED/ACTIVE case can be re-opened to
    RECERTIFICATION_REQUESTED, after which a brand-new PENDING record walks
    PENDING → RECEIVED → COMPLETE. Not a linear A→B→C.
    """

    def test_recertification_creates_new_pending_and_transitions_prior_to_recert_requested(self, api):
        """PRD §3.5: "On success the server creates a new `CertificationRecord` in `PENDING`, transitions the previous `COMPLETE` record to `RECERTIFICATION_REQUESTED`, and issues a `RECERTIFICATION_REQUEST` notice with `response_due_at` fifteen days after `sent_at`."
        PRD §3.5: "The previous-record transition is the cycle endpoint: `COMPLETE → RECERTIFICATION_REQUESTED` on the older record runs in parallel with the new record's own `PENDING → RECEIVED → COMPLETE` path."

        Design: Difficulty/non_linear_state_machine/certification_cycle_complete_to_recert_then_back_to_complete
        """
        bundle = setup_approved_case(
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        cert1_id = bundle.certification["id"]
        # Advance clock more than 30 days from the COMPLETE cert.received_at.
        set_clock("2026-07-10T00:00:00.000Z")
        new_cert = request_recertification(bundle.case["id"])
        cert1_after = get_certification(cert1_id)
        assert cert1_after["certification_status"] == "RECERTIFICATION_REQUESTED", (
            f"Prior COMPLETE cert must move to RECERTIFICATION_REQUESTED; got {cert1_after['certification_status']!r}"
        )
        # Walk the new record forward.
        receive_certification(new_cert["id"])
        cert2_after = mark_certification_complete(new_cert["id"])
        assert cert2_after["certification_status"] == "COMPLETE"
        assert cert2_after["id"] != cert1_id, (
            "request-recertification must create a brand-new record (different id), not flip the existing one"
        )

    def test_recertification_request_advances_case_version(self, api):
        """PRD §3.5: "Note that because opening a recertification bumps the case's `version`, any HR officer holding a stale view of the case at this moment will fail OCC on a subsequent approve attempt — this is the precise scenario `ERR_STALE_VERSION` is designed to catch."

        Design: Difficulty/non_linear_state_machine/certification_cycle_complete_to_recert_then_back_to_complete
        """
        bundle = setup_approved_case(
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        case_version_before = bundle.case["version"]
        set_clock("2026-07-10T00:00:00.000Z")
        request_recertification(bundle.case["id"])
        from test_helpers import get_case

        case_after = get_case(bundle.case["id"])
        assert case_after["version"] > case_version_before, (
            f"opening a recertification must bump the case's version; "
            f"before={case_version_before}, after={case_after['version']!r}"
        )
