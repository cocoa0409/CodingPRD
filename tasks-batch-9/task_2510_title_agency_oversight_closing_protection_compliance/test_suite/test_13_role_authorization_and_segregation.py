"""Endpoint roles, transition roles, agency ownership and the two SoD rules."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    approve_referral,
    assert_appointment_status,
    assert_claim_status,
    assert_money_equal,
    assert_total_count,
    balance_snapshot_payload,
    create_audit,
    create_claim,
    create_escrow_account,
    create_escrow_account_payload,
    create_escrow_audit_payload,
    create_finding,
    create_finding_payload,
    create_policy_file,
    create_policy_file_payload,
    agency_version,
    factories,
    issue_policy,
    onboard_agency,
    read_agency,
    review_audit,
    submit_audit,
    terminate_agency,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST, AUDITOR, COUNSEL, OFFICER

UNKNOWN_ACCOUNT_UUID = "11111111-1111-4111-8111-111111111111"


class TestFindingAuthoringIsExclusive:
    """Only the auditing role may put a finding on the record."""

    def test_neither_the_officer_nor_the_agency_may_author_a_finding(
        self, api, escrow_env
    ):
        """The reviewer and the audited agency are both refused; the auditor is not.

        PRD: "Findings are raised by an `EscrowAuditor` against an audit that is still open
        for writing: the parent audit's `status` must be `SUBMITTED`, `UNDER_REVIEW` or
        `REMEDIATION_REQUIRED`, and a finding written against an already-closed audit is
        refused with `ERR_INVALID_STATE` (HTTP 409), because a closed audit's findings are
        frozen."

        Design: Corner/rbac/exclusive_operations_only_the_escrow_auditor_raises_findings_returns_403
        """
        env, account = escrow_env
        audit = create_audit(api, env, account["id"])

        by_officer = api.create_finding(
            audit["id"],
            create_finding_payload(
                "NEGATIVE_FILE_BALANCE",
                250_000,
                narrative="Officer attempting to author a finding",
            ),
            OFFICER,
        )
        validate_error(by_officer, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        by_agency = api.create_finding(
            audit["id"],
            create_finding_payload(
                "NEGATIVE_FILE_BALANCE",
                250_000,
                narrative="Agency attempting to author a finding",
            ),
            env.principal,
        )
        validate_error(by_agency, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        _rows, empty_meta = validate_paginated(api.list_findings(audit["id"], AUDITOR))
        assert_total_count(empty_meta, 0)

        submit_audit(api, audit["id"])

        finding = create_finding(
            api,
            audit["id"],
            "NEGATIVE_FILE_BALANCE",
            250_000,
            narrative="File 22-118 overdrawn",
        )

        assert finding["severity"] == "HIGH", (
            f"NEGATIVE_FILE_BALANCE is HIGH by code, got {finding['severity']}"
        )
        after = validate_success(api.get_escrow_audit(audit["id"], AUDITOR))
        assert after["risk_tier"] == "HIGH", (
            f"the audit's tier must follow its worst finding, got {after['risk_tier']}"
        )


class TestAppointmentDecisionsAreSplitByRole:
    """One endpoint, two roles, and the refusal is per decision."""

    def test_the_analyst_cannot_terminate_and_the_officer_cannot_suspend(self, api, env):
        """Each role is refused on the other's decision and succeeds on its own.

        PRD: "A role that clears the endpoint gate but fails the transition gate is
        rejected with `ERR_TRANSITION_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/exclusive_operations_termination_and_suspension_are_split_between_roles_returns_403
        """
        analyst_terminating = api.decide_appointment(
            env.agency_id,
            factories.appointment_decision_payload(
                "TERMINATE", termination_reason="VOLUNTARY"
            ),
            ANALYST,
        )
        validate_error(
            analyst_terminating,
            ApiErrorId.ERR_TRANSITION_ROLE_NOT_PERMITTED.value,
            403,
        )

        officer_suspending = api.decide_appointment(
            env.agency_id,
            factories.appointment_decision_payload(
                "SUSPEND", reason="Officer overreach"
            ),
            OFFICER,
        )
        validate_error(
            officer_suspending,
            ApiErrorId.ERR_TRANSITION_ROLE_NOT_PERMITTED.value,
            403,
        )

        untouched = read_agency(api, env.agency_id)
        assert_appointment_status(untouched, "APPOINTED")

        suspended = validate_success(
            api.decide_appointment(
                env.agency_id,
                factories.appointment_decision_payload(
                    "SUSPEND", reason="Escrow concerns"
                ),
                ANALYST,
            )
        )
        assert_appointment_status(suspended, "SUSPENDED")

        terminated = terminate_agency(
            api, env.agency_id, termination_reason="FOR_CAUSE"
        )

        assert_appointment_status(terminated, "TERMINATED")


class TestAuditOpeningIsShared:
    """Two roles share the create; the fifth role has no business there."""

    def test_the_auditor_and_the_officer_may_both_open_an_audit_but_counsel_may_not(
        self, api, env
    ):
        """Each opener's own identifier is recorded, and counsel is refused outright.

        PRD: "Audits are opened by an `EscrowAuditor` or a `ComplianceOfficer` against a
        specific account, carrying the `agency_id`, the `escrow_account_id`, the
        `audit_type` — either `SCHEDULED` or `SURPRISE` — the reconciliation cut-off in
        `as_of_date`, and optionally `follow_up_of_audit_id` pointing at the predecessor
        audit whose findings this one re-tests."

        Design: Corner/rbac/shared_operations_auditor_and_officer_open_audits_counsel_cannot_returns_403
        """
        first_account = create_escrow_account(api, env)
        second_account = create_escrow_account(api, env)

        by_auditor = validate_success(
            api.create_escrow_audit(
                create_escrow_audit_payload(
                    env.agency_id, first_account["id"], as_of_date="2026-07-31"
                ),
                AUDITOR,
            ),
            201,
        )
        by_officer = validate_success(
            api.create_escrow_audit(
                create_escrow_audit_payload(
                    env.agency_id, second_account["id"], as_of_date="2026-07-31"
                ),
                OFFICER,
            ),
            201,
        )

        assert by_auditor["conducted_by_user_id"] == "auditor-1", (
            "the auditor's own identifier must be recorded, got "
            f"{by_auditor['conducted_by_user_id']!r}"
        )
        assert by_officer["conducted_by_user_id"] == "officer-1", (
            "the officer's own identifier must be recorded, got "
            f"{by_officer['conducted_by_user_id']!r}"
        )
        assert by_auditor["status"] == "DRAFT" and by_officer["status"] == "DRAFT", (
            "both openings must land in DRAFT, got "
            f"{by_auditor['status']} and {by_officer['status']}"
        )

        by_counsel = api.create_escrow_audit(
            create_escrow_audit_payload(
                env.agency_id,
                first_account["id"],
                audit_type="SURPRISE",
                as_of_date="2026-07-31",
            ),
            COUNSEL,
        )

        validate_error(by_counsel, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        _rows, meta = validate_paginated(
            api.list_escrow_audits(OFFICER, params={"agency_id": env.agency_id})
        )
        assert_total_count(meta, 2)


class TestAgencyPrincipalsArePeers:
    """Two principals hold identical capabilities over disjoint data."""

    def test_one_agency_principal_cannot_write_against_another_agency(self, api, env):
        """Both a foreign path segment and a foreign body reference are refused.

        PRD: "When `X-User-Role` is `AgencyPrincipal`, `X-User-ID` is the `id` of the
        acting `Agency`; ownership checks on any resource that references an `Agency`
        compare the resource's `agency_id` to `X-User-ID`, and a mismatch is rejected with
        `ERR_AGENCY_OWNERSHIP_REQUIRED` (HTTP 403)."

        Design: Corner/rbac/peer_roles_agency_principal_cannot_act_for_another_agency_returns_403
        """
        neighbour = onboard_agency(api, state_program=env.state_program)
        neighbour_account = create_escrow_account(api, neighbour)
        observed = agency_version(api, env.agency_id)

        foreign_snapshot = api.post_balance_snapshot(
            neighbour_account["id"], balance_snapshot_payload(), env.principal
        )

        validate_error(
            foreign_snapshot, ApiErrorId.ERR_AGENCY_OWNERSHIP_REQUIRED.value, 403
        )
        untouched = validate_success(
            api.get_escrow_account(neighbour_account["id"], OFFICER)
        )
        assert untouched["snapshot_as_of"] is None, (
            "the refused snapshot must leave the account unwritten, got "
            f"{untouched['snapshot_as_of']!r}"
        )

        foreign_file = api.create_policy_file(
            create_policy_file_payload(
                neighbour.agency_id,
                env.state_program_id,
                observed,
                order_number="ORD-9131",
                closing_date="2026-07-10",
            ),
            env.principal,
        )

        validate_error(
            foreign_file, ApiErrorId.ERR_AGENCY_OWNERSHIP_REQUIRED.value, 403
        )

        own_account = validate_success(
            api.create_escrow_account(
                create_escrow_account_payload(
                    env.agency_id,
                    bank_name="First Trust Bank",
                    account_ref="ESCROW-A1",
                ),
                env.principal,
            ),
            201,
        )

        assert own_account["agency_id"] == env.agency_id, (
            "the identical capability over its own agency is unaffected, got "
            f"{own_account['agency_id']}"
        )


class TestSegregationOfDutiesOnAuditClosure:
    """SoD-1 compares the closer against the recorded opener."""

    def test_the_officer_who_opened_the_audit_cannot_close_it(
        self,
        api,
        escrow_env,
        second_escrow_auditor_headers,
        second_compliance_officer_headers,
    ):
        """The opener may review the audit but a second officer must close it.

        PRD: "The `X-User-ID` closing an escrow audit, whether to `CLOSED_CLEAN` or to
        `CLOSED_ADVERSE`, must differ from the `conducted_by_user_id` recorded when that
        audit was opened."

        Design: Corner/rbac/segregation_of_duties_audit_opener_cannot_close_its_own_audit_returns_403
        """
        env, account = escrow_env
        audit = validate_success(
            api.create_escrow_audit(
                create_escrow_audit_payload(
                    env.agency_id, account["id"], as_of_date="2026-07-31"
                ),
                OFFICER,
            ),
            201,
        )
        assert audit["conducted_by_user_id"] == "officer-1", (
            "the opening officer is the SoD-1 anchor, got "
            f"{audit['conducted_by_user_id']!r}"
        )
        submit_audit(api, audit["id"], headers=second_escrow_auditor_headers)
        reviewed = review_audit(api, audit["id"])
        assert reviewed["status"] == "UNDER_REVIEW", (
            "the opener may still advance the audit to review, got "
            f"{reviewed['status']}"
        )

        self_closure = api.transition_audit(
            audit["id"],
            factories.audit_state_payload("CLOSED_CLEAN", note="Self-closure attempt"),
            OFFICER,
        )

        validate_error(self_closure, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
        still_open = validate_success(api.get_escrow_audit(audit["id"], AUDITOR))
        assert still_open["status"] == "UNDER_REVIEW", (
            f"the refused closure must leave the audit UNDER_REVIEW, got {still_open['status']}"
        )

        closed = validate_success(
            api.transition_audit(
                audit["id"],
                factories.audit_state_payload(
                    "CLOSED_CLEAN", note="Independent review complete"
                ),
                second_compliance_officer_headers,
            )
        )

        assert closed["status"] == "CLOSED_CLEAN", (
            f"an independent officer must be able to close it, got {closed['status']}"
        )
        assert closed["closed_by_user_id"] == "officer-2", (
            f"the closing officer is recorded, got {closed['closed_by_user_id']!r}"
        )


class TestSegregationOfDutiesOnClaimAdjudication:
    """SoD-2 is scoped to the one policy file the counsel approved."""

    def test_the_counsel_who_cleared_the_referral_cannot_adjudicate_the_claim(
        self, api, env, second_underwriting_counsel_headers
    ):
        """Both adjudication outcomes are barred to counsel-1 and open to counsel-2.

        PRD: "The `X-User-ID` adjudicating a claim out of `INVESTIGATING`, whether to
        `RECOURSE_DEMANDED` or to `ABSORBED`, must differ from the
        `referral_decided_by_user_id` recorded on the claim's linked policy file."

        Design: Corner/rbac/segregation_of_duties_referral_approver_cannot_adjudicate_that_claim_returns_403
        """
        policy_file = create_policy_file(
            api,
            env,
            closing_date="2026-07-20",
            liability_amount_cents=80_000_000,
            gross_premium_cents=500_000,
        )
        assert policy_file["issuance_status"] == "PENDING_REFERRAL", (
            "80,000,000 is above the authority limit, so the file must be referred, got "
            f"{policy_file['issuance_status']}"
        )
        approved = approve_referral(api, policy_file["id"], 80_000_000)
        assert approved["referral_decided_by_user_id"] == "counsel-1", (
            "the approving counsel is the SoD-2 anchor, got "
            f"{approved['referral_decided_by_user_id']!r}"
        )
        issue_policy(api, env, policy_file["id"], policy_number="POL-9141")
        claim = create_claim(
            api,
            env,
            policy_file["id"],
            cause_code="AGENCY_ERROR",
            loss_amount_cents=40_000_000,
        )

        self_demand = api.transition_claim(
            claim["id"],
            factories.claim_state_payload(
                "RECOURSE_DEMANDED", note="Same counsel adjudicating own referral"
            ),
            COUNSEL,
        )
        validate_error(self_demand, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        self_absorb = api.transition_claim(
            claim["id"],
            factories.claim_state_payload(
                "ABSORBED", note="Same counsel absorbing own referral"
            ),
            COUNSEL,
        )
        validate_error(self_absorb, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

        assert_claim_status(
            validate_success(api.get_claim(claim["id"], OFFICER)), "INVESTIGATING"
        )

        demanded = validate_success(
            api.transition_claim(
                claim["id"],
                factories.claim_state_payload(
                    "RECOURSE_DEMANDED", note="Independent review: agency error"
                ),
                second_underwriting_counsel_headers,
            )
        )

        assert_claim_status(demanded, "RECOURSE_DEMANDED")
        assert demanded["recourse_tier"] == "TIER_1", (
            f"a gross ratio of 0.20 pins TIER_1, got {demanded['recourse_tier']}"
        )
        assert_money_equal(
            demanded["recourse_amount_cents"], 12_000_000, "recourse_amount_cents"
        )
        assert demanded["decided_by_user_id"] == "counsel-2", (
            f"the independent counsel is recorded, got {demanded['decided_by_user_id']!r}"
        )


class TestPrecedenceOfTheRoleGate:
    """The role gate answers before any body reference is resolved."""

    def test_an_unauthorized_role_is_refused_before_the_unknown_body_references(
        self, api
    ):
        """Two unresolvable foreign keys never get looked at against an empty database.

        PRD: "When more than one rule would reject a request, the outcome is fully
        determined: rules are evaluated in the following precedence order, and the first
        failure is returned. Nothing later in the ladder is evaluated once an earlier tier
        has rejected."

        Design: Corner/validations/priority_ordering_role_check_outranks_body_fk_resolution_returns_403
        """
        response = api.create_escrow_audit(
            create_escrow_audit_payload(
                NON_EXISTENT_UUID, UNKNOWN_ACCOUNT_UUID, as_of_date="2026-07-31"
            ),
            ANALYST,
        )

        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
        error_id = response.json()["data"]["error_id"]
        assert error_id not in (
            ApiErrorId.ERR_AGENCY_NOT_FOUND.value,
            ApiErrorId.ERR_ESCROW_ACCOUNT_NOT_FOUND.value,
        ), (
            "the priority-20 role failure outranks both body-reference failures, got "
            f"{error_id}"
        )
