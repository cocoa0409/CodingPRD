"""Review loop, approval quorum, segregation of duties, and exception grants."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_engagement,
    build_user_headers,
    create_engagement,
    create_jurisdiction,
    create_contractor,
    get_engagement,
    grant_exception,
    make_answers,
    record_approval,
    run_determination,
    setup_engagement_at_state,
    setup_high_tier_engagement,
    submit_for_approval,
    submit_for_review,
    submit_questionnaire,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

_MANAGER = TEST_USERS["engagement_manager_headers"]
_ANALYST = TEST_USERS["classification_analyst_headers"]
_ADMIN = TEST_USERS["platform_admin_headers"]
_BOARD = TEST_USERS["compliance_board_member_headers"]


class TestReviewLoop:
    def test_review_loop_cycle_and_stale_determination(self, api, classification_analyst_headers):
        """PRD §3.3: "When a review has been suspended for more information — the
        engagement sitting in `INFO_REQUESTED` — a questionnaire resubmission answers
        the request and returns the engagement to `UNDER_REVIEW`."
        PRD §3.4: "the current determination's `questionnaire_revision` must equal the
        questionnaire's current `revision`; a determination computed from an older
        revision is stale and the submission is rejected with `ERR_DETERMINATION_STALE`
        (HTTP 409)."

        Design: Corner/state_machines/sm_review_loop_cycle_and_stale_determination
        """
        setup = setup_engagement_at_state("UNDER_REVIEW")
        engagement = setup["engagement"]

        info = validate_success(
            api.request_info(engagement["id"], {"reason": "Clarify control method"},
                             classification_analyst_headers),
            200,
        )
        assert info["status"] == "INFO_REQUESTED"

        q = validate_success(
            api.submit_questionnaire(
                engagement["id"],
                {"answers": make_answers(PERMANENCY="YES")},
                _MANAGER,
            ),
            200,
        )
        assert q["revision"] == 2

        back = get_engagement(engagement["id"])
        assert back["status"] == "UNDER_REVIEW"

        res = api.submit_approval(engagement["id"], classification_analyst_headers)
        validate_error(res, ApiErrorId.ERR_DETERMINATION_STALE.value)

    def test_submit_review_requires_current_determination(self, api, engagement_manager_headers):
        """PRD §3.4: "This step requires a current determination to exist — otherwise
        `ERR_DETERMINATION_REQUIRED` (HTTP 409)".
        PRD §2.9: "Entries within a rung share priority." — submit-review from
        INTAKE_SUBMITTED fails both the generic state check and the determination
        requirement at the same rung, so either rung-5 code satisfies the contract.

        Design: Corner/validations/val_determination_required_for_submit_review
        """
        setup = setup_engagement_at_state("INTAKE_SUBMITTED")
        res = api.submit_review(setup["engagement"]["id"], engagement_manager_headers)
        actual = validate_error_is_one_of(
            res, [ApiErrorId.ERR_DETERMINATION_REQUIRED.value, ApiErrorId.ERR_INVALID_STATE.value]
        )
        assert actual in (
            ApiErrorId.ERR_DETERMINATION_REQUIRED.value,
            ApiErrorId.ERR_INVALID_STATE.value,
        )


class TestApprovalQuorum:
    def test_approve_outside_approval_pending_rejected(self, api, hr_approver_headers):
        """PRD §3.5: "Each approval call is valid only while the engagement is in
        `APPROVAL_PENDING` — an approval attempted in any other status is rejected
        with `ERR_ENGAGEMENT_NOT_APPROVAL_PENDING` (HTTP 409)".

        Design: Corner/validations/val_approve_requires_approval_pending
        """
        setup = setup_engagement_at_state("UNDER_REVIEW")
        res = api.approve_engagement(setup["engagement"]["id"], hr_approver_headers)
        validate_error(res, ApiErrorId.ERR_ENGAGEMENT_NOT_APPROVAL_PENDING.value)
        fresh = get_engagement(setup["engagement"]["id"])
        assert fresh["status"] == "UNDER_REVIEW"
        assert fresh["approvals_recorded"] == []

    def test_approval_out_of_order_legal_first_rejected(self, api, legal_approver_headers):
        """PRD §3.5: "The approval sequence is fixed as `HRApprover` first, then
        `LegalApprover`, then `ComplianceBoardMember`, truncated to the engagement's
        `required_approval_count`" and "the acting principal's role must equal the role
        at the next unfilled position of the truncated sequence, otherwise the call is
        rejected with `ERR_APPROVAL_OUT_OF_ORDER` (HTTP 409)."
        PRD §3.4: "`ELEVATED` when the outcome is `CONTRACTOR` under a jurisdiction
        applying `ABC_TEST` or `ECONOMIC_REALITY`"; "`ELEVATED` requires two".

        Design: Corner/validations/val_approval_out_of_order_legal_first_rejected
        """
        setup = setup_engagement_at_state(
            "APPROVAL_PENDING",
            jurisdiction_overrides={
                "code": "US-CA",
                "test_type": "ABC_TEST",
                "state_filing_threshold_cents": 0,
            },
        )
        engagement = setup["engagement"]
        assert engagement["risk_tier"] == "ELEVATED"
        assert engagement["required_approval_count"] == 2

        res = api.approve_engagement(engagement["id"], legal_approver_headers)
        validate_error(res, ApiErrorId.ERR_APPROVAL_OUT_OF_ORDER.value)
        fresh = get_engagement(engagement["id"])
        assert fresh["approvals_recorded"] == []

    def test_approver_already_acted_rejected(self, api):
        """PRD §3.5: "Segregation of duties is enforced across the round: a principal
        whose `X-User-ID` already appears among the recorded approvals cannot act
        again, and a repeat attempt is rejected with `ERR_APPROVER_ALREADY_ACTED`
        (HTTP 409)."

        Design: Corner/validations/val_approver_already_acted_sod
        """
        setup = setup_high_tier_engagement("APPROVAL_PENDING")
        engagement = setup["engagement"]
        grant_exception(engagement["id"])

        record_approval(engagement["id"], "HRApprover", "hr-001")
        record_approval(engagement["id"], "LegalApprover", "legal-001")

        # Correct role for step 3, but hr-001 already occupies step 1.
        res = api.approve_engagement(
            engagement["id"], build_user_headers("hr-001", "ComplianceBoardMember")
        )
        validate_error(res, ApiErrorId.ERR_APPROVER_ALREADY_ACTED.value)
        fresh = get_engagement(engagement["id"])
        assert fresh["status"] == "APPROVAL_PENDING"
        assert len(fresh["approvals_recorded"]) == 2

    def test_elevated_two_step_quorum_completes(self, api):
        """PRD §3.5: "The approval sequence is fixed as `HRApprover` first, then
        `LegalApprover`, then `ComplianceBoardMember`, truncated to the engagement's
        `required_approval_count`: a `STANDARD` engagement needs only the `HRApprover`
        step, an `ELEVATED` engagement needs `HRApprover` then `LegalApprover`, and a
        `HIGH` engagement needs all three in that order."
        PRD §3.5: "Each accepted approval appends an entry recording the acting `role`,
        the acting `user_id`, and the `decided_at` instant to `approvals_recorded`;
        when the entry count reaches `required_approval_count`, the engagement
        automatically transitions to `APPROVED`."

        Design: Corner/rbac/rbac_elevated_two_step_quorum_completion
        """
        setup = setup_engagement_at_state(
            "APPROVAL_PENDING",
            jurisdiction_overrides={
                "code": "US-CA",
                "test_type": "ABC_TEST",
                "state_filing_threshold_cents": 0,
            },
        )
        engagement = setup["engagement"]
        assert engagement["required_approval_count"] == 2

        mid = validate_success(
            api.approve_engagement(engagement["id"], build_user_headers("hr-001", "HRApprover")),
            200,
        )
        assert mid["status"] == "APPROVAL_PENDING"
        assert len(mid["approvals_recorded"]) == 1

        end = validate_success(
            api.approve_engagement(engagement["id"], build_user_headers("legal-001", "LegalApprover")),
            200,
        )
        assert end["status"] == "APPROVED"
        entries = end["approvals_recorded"]
        assert len(entries) == 2
        assert entries[0]["role"] == "HRApprover" and entries[0]["user_id"] == "hr-001"
        assert entries[1]["role"] == "LegalApprover" and entries[1]["user_id"] == "legal-001"

    def test_high_tier_final_approval_without_exception_rejected(self, api):
        """PRD §3.5: "When the approval being recorded is the one that reaches quorum
        on a `HIGH` tier engagement, an ExceptionGrant with status `ACTIVE` whose
        `expires_at` has not passed must exist for the engagement. If no such grant
        exists, the approval is rejected with `ERR_EXCEPTION_REQUIRED` (HTTP 422);
        if a grant exists but has expired against the logical clock, the rejection is
        `ERR_EXCEPTION_EXPIRED` (HTTP 422)."

        Design: Corner/validations/val_high_tier_final_approval_without_exception_rejected
        """
        # Grant-free HIGH pipeline: ABC_TEST jurisdiction + CONTROL_METHOD=YES yields
        # EMPLOYEE_RISK (PRD §3.1), which fixes risk_tier HIGH and a 3-step quorum.
        setup = setup_engagement_at_state(
            "APPROVAL_PENDING",
            jurisdiction_overrides={
                "code": "US-CA",
                "test_type": "ABC_TEST",
                "state_filing_threshold_cents": 0,
            },
            answers=make_answers(CONTROL_METHOD="YES"),
        )
        engagement = setup["engagement"]
        assert engagement["risk_tier"] == "HIGH"
        assert engagement["required_approval_count"] == 3

        record_approval(engagement["id"], "HRApprover", "hr-001")
        record_approval(engagement["id"], "LegalApprover", "legal-001")
        res = api.approve_engagement(engagement["id"], build_user_headers("board-001", "ComplianceBoardMember"))
        validate_error(res, ApiErrorId.ERR_EXCEPTION_REQUIRED.value)
        fresh = get_engagement(engagement["id"])
        assert fresh["status"] == "APPROVAL_PENDING"
        assert len(fresh["approvals_recorded"]) == 2


class TestActivationStateGate:
    def test_activate_from_classified_rejected(self, api, engagement_manager_headers):
        """PRD §3.5: "Once `APPROVED`, an engagement becomes operational through
        activation by an `EngagementManager`."
        PRD §2.9: "Entries within a rung share priority." — from CLASSIFIED both the
        generic invalid-transition check and the executed-contract requirement (both
        state-validity rung) fail, so either rung-5 code satisfies the contract.

        Design: Corner/state_machines/sm_activate_from_classified_rejected
        """
        setup = setup_engagement_at_state("CLASSIFIED")
        res = api.activate_engagement(setup["engagement"]["id"], engagement_manager_headers)
        validate_error_is_one_of(
            res, [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_CONTRACT_NOT_EXECUTED.value]
        )
        fresh = get_engagement(setup["engagement"]["id"])
        assert fresh["status"] == "CLASSIFIED"

    def test_terminal_engagement_rejects_submit_review(self, api, engagement_manager_headers):
        """PRD §2.9: "This rung covers the generic `ERR_INVALID_STATE` (HTTP 409)
        rejection — including terminal lockdown of `REJECTED`, `TERMINATED`, or
        `CONVERTED` engagements, `VOID` or `SUPERSEDED` filings, `CLOSED` audits and
        reviews, terminal amendments, `RESOLVED` inquiries, and terminal conversions".
        PRD §3.6: "Termination, also by a `ComplianceOfficer`, moves an engagement from
        `ACTIVE` or `SUSPENDED` to the terminal `TERMINATED` status, and the
        engagement's contract — whether `EXECUTED` or `SUSPENDED` — transitions to
        `TERMINATED` with it."

        Design: Corner/state_machines/sm_terminal_engagement_rejects_submit_review
        """
        setup = setup_engagement_at_state("TERMINATED")
        engagement = setup["engagement"]
        assert engagement["status"] == "TERMINATED"
        assert setup["contract"]["status"] == "TERMINATED"

        res = api.submit_review(engagement["id"], engagement_manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        fresh = get_engagement(engagement["id"])
        assert fresh["status"] == "TERMINATED"


class TestExceptionGrants:
    def test_exception_capacity_reached_at_boundary(self, api, compliance_board_member_headers):
        """PRD §3.5: "Capacity is capped per regime: the count of `ACTIVE` grants
        across all engagements of the jurisdiction must be strictly below the
        jurisdiction's `max_active_exceptions` before another grant is issued, and a
        grant attempted at capacity is rejected with `ERR_EXCEPTION_CAPACITY_REACHED`
        (HTTP 422)."

        Design: Corner/validations/val_exception_capacity_boundary
        """
        jurisdiction = create_jurisdiction(
            code="US-CA", test_type="ABC_TEST", state_filing_threshold_cents=0,
            max_active_exceptions=1,
        )
        contractor = create_contractor()
        eng1 = create_engagement(contractor["id"], jurisdiction["id"], title="Cap one")
        eng2 = create_engagement(contractor["id"], jurisdiction["id"], title="Cap two")

        first = api.create_exception(
            eng1["id"],
            {"justification": "First slot", "expires_at": "2027-01-31T00:00:00Z"},
            compliance_board_member_headers,
        )
        validate_success(first, 201)

        res = api.create_exception(
            eng2["id"],
            {"justification": "Second slot attempt", "expires_at": "2027-01-31T00:00:00Z"},
            compliance_board_member_headers,
        )
        validate_error(res, ApiErrorId.ERR_EXCEPTION_CAPACITY_REACHED.value)

        grants, _ = validate_paginated(api.list_exceptions(eng1["id"], _ADMIN))
        active = [g for g in grants if g["status"] == "ACTIVE"]
        assert len(active) == 1

    def test_state_error_beats_capacity_error_on_terminated_engagement(
        self, api, compliance_board_member_headers
    ):
        """PRD §2.9: "Every request passes through a fixed ladder of validation rungs,
        evaluated in the order below; a request that fails an earlier rung is rejected
        immediately and never surfaces a later rung's error." — state validity (rung 5,
        including terminal lockdown of `TERMINATED` engagements) precedes fiscal
        capacity (rung 10, `ERR_EXCEPTION_CAPACITY_REACHED`).

        Design: Difficulty/priority_pair_validation_conflict/ppv_state_vs_fiscal_on_exception_grant
        """
        setup = setup_engagement_at_state(
            "TERMINATED",
            jurisdiction_overrides={"max_active_exceptions": 0},
        )
        engagement = setup["engagement"]
        assert engagement["status"] == "TERMINATED"

        res = api.create_exception(
            engagement["id"],
            {"justification": "Late exception attempt", "expires_at": "2027-01-31T00:00:00Z"},
            compliance_board_member_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_rejected_exception_grant_leaves_no_trace(
        self, api, compliance_board_member_headers
    ):
        """PRD §2.9: "a request that fails an earlier rung is rejected immediately and
        never surfaces a later rung's error" — the terminal-lockdown rejection must not
        consume capacity or persist a grant.
        PRD §3.5: "The exception grants of an engagement are retrievable as a list".

        Design: Difficulty/priority_pair_validation_conflict/ppv_state_vs_fiscal_on_exception_grant
        """
        setup = setup_engagement_at_state(
            "TERMINATED",
            jurisdiction_overrides={"max_active_exceptions": 0},
        )
        engagement = setup["engagement"]

        res = api.create_exception(
            engagement["id"],
            {"justification": "Late exception attempt", "expires_at": "2027-01-31T00:00:00Z"},
            compliance_board_member_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

        grants, _ = validate_paginated(api.list_exceptions(engagement["id"], _ADMIN))
        assert grants == [], "a rejected grant attempt must not persist"
        fresh = get_engagement(engagement["id"])
        assert fresh["status"] == "TERMINATED"
