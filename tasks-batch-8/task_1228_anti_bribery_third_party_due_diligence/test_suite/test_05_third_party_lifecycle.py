"""Third-party approval gates, lifecycle lockdown, training gate, termination."""
import pytest

from test_helpers import (
    ApiErrorId,
    admin_headers,
    approve_payment,
    approve_third_party,
    create_active_policy,
    create_country,
    create_draft_third_party,
    create_gift,
    create_payment,
    create_red_flag,
    get_third_party,
    issue_questionnaire,
    officer_headers,
    set_clock,
    setup_active_contract,
    setup_risk_basis,
    setup_third_party_in_state,
    sponsor_headers,
    submit_questionnaire,
    submit_third_party,
    training_assignment_payload,
    walk_to_questionnaire_accepted,
    FINANCE_1_ID,
    SPONSOR_1_ID,
    SPONSOR_9_ID,
    validate_error,
    validate_success,
)


class TestApprovalGates:
    def test_approve_without_accepted_questionnaire_rejected(self, api, officer_headers):
        """PRD §3.5: "Approval — permitted only from `DD_REVIEW` — first requires
        a referential triple, evaluated under §2.9's priority order with the
        active-policy check listed first: exactly one scoring policy must be
        `ACTIVE` (`ERR_POLICY_NOT_ACTIVE`); the current questionnaire must be
        `ACCEPTED`, which is precisely the condition that `risk_score_final` is
        non-null (`ERR_QUESTIONNAIRE_NOT_ACCEPTED`); and the party must hold no
        `OPEN` or `UNDER_ENHANCED_REVIEW` red flag and no `ENHANCED_DD`
        escalation case — a single error, `ERR_RED_FLAGS_OPEN`, covers both,
        because an open case always implies an escalated flag."

        Design: Corner/state_machines/approve_without_accepted_questionnaire_rejected
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        q = issue_questionnaire(tp_id)
        submit_questionnaire(q["id"])  # SUBMITTED but never ACCEPTED

        resp = api.approve_third_party(tp_id, officer_headers)
        validate_error(resp, ApiErrorId.ERR_QUESTIONNAIRE_NOT_ACCEPTED)
        assert get_third_party(tp_id)["onboarding_status"] == "DD_REVIEW"

    def test_approve_with_open_red_flag_rejected(self, api, officer_headers):
        """PRD §3.5: "the party must hold no `OPEN` or `UNDER_ENHANCED_REVIEW`
        red flag and no `ENHANCED_DD` escalation case — a single error,
        `ERR_RED_FLAGS_OPEN`, covers both, because an open case always implies an
        escalated flag."

        Design: Corner/state_machines/approve_with_open_red_flag_rejected
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        walk_to_questionnaire_accepted(tp_id)
        create_red_flag(tp_id, "u_co1", severity="LOW", description="incomplete references")

        resp = api.approve_third_party(tp_id, officer_headers)
        validate_error(resp, ApiErrorId.ERR_RED_FLAGS_OPEN)
        assert get_third_party(tp_id)["onboarding_status"] == "DD_REVIEW"

    def test_business_sponsor_cannot_approve_third_party(self, api, sponsor_headers):
        """PRD §2.1: "A request whose role is not in the endpoint's authorized
        role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4 lists POST /compliance/third-parties/{third_party_id}/approve
        with ComplianceOfficer as its only authorized role.

        Design: Corner/rbac/business_sponsor_cannot_approve_third_party
        """
        ctx = setup_third_party_in_state("DD_REVIEW", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        walk_to_questionnaire_accepted(tp_id)

        resp = api.approve_third_party(tp_id, sponsor_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_third_party(tp_id)["onboarding_status"] == "DD_REVIEW"


class TestTerminalLockdown:
    def test_suspend_on_terminated_third_party_rejected(self, api, officer_headers):
        """PRD §2.10: "Terminal states — `REJECTED` and `TERMINATED` for a third
        party; `CLEAR`, `HIT_CONFIRMED`, and `HIT_DISMISSED` for a check;
        `ACCEPTED` and `SUPERSEDED` for a questionnaire; `CLEARED` and
        `SUBSTANTIATED` for a red flag; `DECIDED` for a case; `EXPIRED` and
        `TERMINATED` for a contract; `BLOCKED` and `REVERSED` for a payment;
        `REJECTED` and `VOIDED` for a gift entry; `COMPLETED` for a cycle;
        `CLOSED` for an audit; `COMPLETED` for a training assignment;
        `SUPERSEDED` for a policy — are locked: any further action attempted
        against an entity in one of them is rejected with `ERR_ALREADY_TERMINAL`
        (HTTP 409), while a transition the machine does not permit from the
        entity's current non-terminal state is rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/suspend_on_terminated_third_party_rejected
        """
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        validate_success(
            api.terminate_third_party(tp_id, {"reason": "sanctions designation"},
                                      officer_headers), 200)

        resp = api.suspend_third_party(tp_id, {"reason": "too late"}, officer_headers)
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)


class TestSubmitGates:
    def test_submit_without_active_policy_rejected(self, api, admin_headers, sponsor_headers):
        """PRD §3.1: "Both the submit and the approve paths in the onboarding
        flow demand that exactly one active policy exist; when none does, they
        fail with `ERR_POLICY_NOT_ACTIVE` (HTTP 422)."

        Design: Corner/validations/submit_without_active_policy_rejected
        """
        set_clock()
        create_country("CH", 80)
        # Policy created but deliberately left in DRAFT — never activated.
        from test_helpers import policy_payload
        validate_success(api.create_policy(policy_payload(), admin_headers), 201)
        tp = create_draft_third_party("CH", "TECHNOLOGY", "NONE")

        resp = api.submit_third_party(tp["id"], sponsor_headers)
        validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE)
        assert get_third_party(tp["id"])["onboarding_status"] == "DRAFT"

    def test_submit_with_overdue_training_rejected(self, api, admin_headers):
        """PRD §3.2: "the caller must hold no training assignment in `OVERDUE`
        status (`ERR_SPONSOR_TRAINING_OVERDUE`)"
        PRD §3.9: "Completion moves `ASSIGNED` or `OVERDUE` to `COMPLETED` — late
        completion is allowed — and is self-service for the assignee, whose
        `assignee_user_id` must equal their own caller identity, or available to
        any `ComplianceAdmin`."

        Design: Corner/validations/submit_with_overdue_training_rejected
        """
        setup_risk_basis("CH", 80)
        tr = validate_success(
            api.create_training_assignment(
                training_assignment_payload(assignee_user_id=SPONSOR_9_ID,
                                            course_code="ABAC-101", due_date="2026-04-30"),
                admin_headers,
            ), 201)
        # Move the clock past the due date so the sweep flips it to OVERDUE.
        set_clock("2026-05-02T00:00:00Z")
        rows = validate_success(
            api.list_training_assignments(admin_headers,
                                          params={"assignee_user_id": SPONSOR_9_ID}), 200)
        assert rows[0]["training_status"] == "OVERDUE"

        tp = create_draft_third_party("CH", "TECHNOLOGY", "NONE", sponsor_id=SPONSOR_9_ID,
                                      legal_name="SP9 Ventures")
        blocked = api.submit_third_party(tp["id"], sponsor_headers(SPONSOR_9_ID))
        validate_error(blocked, ApiErrorId.ERR_SPONSOR_TRAINING_OVERDUE)

        done = validate_success(
            api.complete_training_assignment(tr["id"], sponsor_headers(SPONSOR_9_ID)), 200)
        assert done["training_status"] == "COMPLETED", "late completion from OVERDUE"

        submitted = api.submit_third_party(tp["id"], sponsor_headers(SPONSOR_9_ID))
        assert validate_success(submitted, 200)["onboarding_status"] == "SCREENING"


class TestTerminationCascade:
    def test_terminate_endpoint_cascades_to_contracts_payments_gifts(self, api, officer_headers,
                                                                     finance_headers):
        """PRD §3.5: "Termination, from `APPROVED` or `SUSPENDED` — whether by
        officer action with an optional `reason`, by an escalation decision of
        `TERMINATE`, or by a re-diligence completion of `TERMINATE` — fires the
        full cascade: every contract of the party in `DRAFT`, `PENDING_CLAUSES`,
        or `ACTIVE` moves to `TERMINATED`; every payment request still
        `SUBMITTED` on those contracts moves to `BLOCKED`; every gift entry still
        `PENDING_APPROVAL` moves to `REJECTED`; and the party's `version`
        increments by one."

        Design: Corner/cross_cutting_complexity_layers/terminate_endpoint_cascades_to_contracts_payments_gifts
        """
        ctx = setup_third_party_in_state("APPROVED", "CH", 80)
        tp_id = ctx["third_party"]["id"]
        contract = setup_active_contract(tp_id, SPONSOR_1_ID, value_cents=500000)
        ct_id = contract["id"]

        p_ok = create_payment(ct_id, amount_cents=40000)
        approve_payment(p_ok["id"], FINANCE_1_ID)
        p_new = create_payment(ct_id, amount_cents=30000)
        gift = create_gift(tp_id, recipient_is_government_official=False,
                           value_cents=4000, event_date="2026-05-10")

        term = validate_success(
            api.terminate_third_party(tp_id, {"reason": "sanctions designation"},
                                      officer_headers), 200)
        assert term["onboarding_status"] == "TERMINATED"

        contract_after = validate_success(api.get_contract(ct_id, officer_headers), 200)
        assert contract_after["contract_status"] == "TERMINATED"
        assert contract_after["approved_payments_total_cents"] == 40000, (
            "approved payments are not rewritten by termination"
        )

        payments = validate_success(api.list_payment_requests(ct_id, finance_headers), 200)
        by_id = {p["id"]: p for p in payments}
        assert by_id[p_ok["id"]]["payment_status"] == "APPROVED"
        assert by_id[p_new["id"]]["payment_status"] == "BLOCKED"

        gifts = validate_success(api.list_gift_entries(tp_id, officer_headers), 200)
        by_gid = {g["id"]: g for g in gifts}
        assert by_gid[gift["id"]]["entry_status"] == "REJECTED"
