"""Disbursement pipeline: fiscal guards, routing, segregation of duties, and
conservation (PRD §2.6, §2.9, §3.4)."""
from test_helpers import (
    ApiErrorId,
    amend_agreement_payload,
    assert_fund_conservation,
    compliance_approve_disbursement,
    create_active_bundle,
    create_approved_disbursement,
    create_disbursement_draft,
    create_paid_disbursement,
    create_received_donation,
    create_submitted_disbursement,
    create_tranche,
    get_fund,
    make_compliance_officer_headers,
    make_finance_officer_headers,
    make_project_lead_headers,
    make_sponsor_admin_headers,
    pay_disbursement,
    pledge_donation,
    report_incident,
    review_decision_payload,
    submit_disbursement,
    suspend_project,
    reinstate_project,
    validate_error,
    validate_success,
)


class TestFiscalGuardsAtSubmit:
    def test_settled_basis_rejects_over_balance_submit(self, api):
        """PRD §3.4: "The amount must not exceed the spendable balance under the
        agreement's `spending_basis` variant from §2.6 — the settled figure under
        `SETTLED`, the pledge-credited figure under `FORWARD_LOOKING` — else
        `ERR_INSUFFICIENT_FUNDS`."
        Settled available is 92,000 (100,000 received less the 8,000 fee); the 50,000
        PLEDGED gift is excluded, so 120,000 is rejected.

        Design: Difficulty/dual_variant_calc/spend_basis_settled_vs_forward
        """
        bundle = create_active_bundle("user_app_c", project_name="Gamma", contact_email="g@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        pledge_donation(pid, 50000)  # stays PLEDGED — excluded from the settled figure

        draft = create_disbursement_draft(pid, 120000, purpose="equipment",
                                          payee_name="Acme", spend_date="2026-06-15")
        resp = api.submit_disbursement(draft["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS)
        after = validate_success(api.get_disbursement(draft["id"], make_sponsor_admin_headers()))
        assert after["status"] == "DRAFT"
        assert get_fund(bundle["fund_account_id"])["committed_cents"] == 0

    def test_forward_looking_basis_accepts_same_amount(self, api):
        """PRD §3.4: "The amount must not exceed the spendable balance under the
        agreement's `spending_basis` variant from §2.6 — the settled figure under
        `SETTLED`, the pledge-credited figure under `FORWARD_LOOKING` — else
        `ERR_INSUFFICIENT_FUNDS`."
        PRD §2.6: "A second derived figure, `forward_available_cents`, adds a pledge
        credit to the settled figure: eighty percent of the sum of `amount_cents` over
        the project's donations still in `PLEDGED`"
        Forward figure: 92,000 + 0.8 x 50,000 = 132,000 >= 120,000.

        Design: Difficulty/dual_variant_calc/spend_basis_settled_vs_forward
        """
        bundle = create_active_bundle("user_app_c2", project_name="Gamma2",
                                      contact_email="g2@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        pledge_donation(pid, 50000)

        agreement = validate_success(api.get_agreement(
            bundle["agreement_id"], make_sponsor_admin_headers()))
        amended = validate_success(api.amend_agreement(
            bundle["agreement_id"],
            amend_agreement_payload(agreement["version"], spending_basis="FORWARD_LOOKING"),
            make_sponsor_admin_headers()))
        assert amended["spending_basis"] == "FORWARD_LOOKING"

        submitted = create_submitted_disbursement(pid, 120000, purpose="equipment 2",
                                                  payee_name="Acme", spend_date="2026-06-16")
        assert submitted["status"] == "SUBMITTED"
        fund = get_fund(bundle["fund_account_id"])
        assert fund["committed_cents"] == 120000
        assert fund["available_cents"] == -28000, "92,000 settled less 120,000 committed"
        assert fund["forward_available_cents"] == 12000, "132,000 forward less 120,000 committed"

    def test_grant_submit_without_covering_tranche(self, api):
        """PRD §3.4: "Under `PRE_APPROVED_GRANT`, exactly one `ISSUED` tranche whose
        closed period covers the `spend_date` must exist — the overlap rule of §3.2
        guarantees uniqueness — and its id is resolved into the request's
        `grant_tranche_id` at this moment; absence of a covering tranche is
        `ERR_NO_COVERING_TRANCHE`."
        spend_date 2026-05-01 falls outside [2026-01-01, 2026-03-31].

        Design: Corner/validations/v_grant_submit_without_covering_tranche
        """
        bundle = create_active_bundle("user_c_v7", model="PRE_APPROVED_GRANT",
                                      project_name="GT", contact_email="gt@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 200000)
        create_tranche(bundle["agreement_id"], amount_cents=100000,
                       period_start="2026-01-01", period_end="2026-03-31", purpose="q1")
        draft = create_disbursement_draft(pid, 50000, purpose="may spend",
                                          spend_date="2026-05-01")
        resp = api.submit_disbursement(draft["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_NO_COVERING_TRANCHE)
        after = validate_success(api.get_disbursement(draft["id"], make_sponsor_admin_headers()))
        assert after["status"] == "DRAFT"
        assert get_fund(bundle["fund_account_id"])["committed_cents"] == 0

    def test_grant_submit_tranche_budget_exceeded(self, api):
        """PRD §3.4: "Under the grant model, the covering tranche's remaining budget —
        its `amount_cents` minus `spent_cents` minus `committed_cents` — must be at
        least the request amount, else `ERR_TRANCHE_BUDGET_EXCEEDED`."
        Remaining 50,000 < 60,000 while the fund-level balance (194,000) suffices.

        Design: Corner/validations/v_grant_submit_tranche_budget_exceeded
        """
        bundle = create_active_bundle("user_c_v8", model="PRE_APPROVED_GRANT",
                                      project_name="TB", contact_email="tb@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 200000)
        create_tranche(bundle["agreement_id"], amount_cents=50000,
                       period_start="2026-01-01", period_end="2026-03-31",
                       purpose="q1 small")
        draft = create_disbursement_draft(pid, 60000, purpose="over tranche",
                                          spend_date="2026-02-01")
        resp = api.submit_disbursement(draft["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_TRANCHE_BUDGET_EXCEEDED)
        after = validate_success(api.get_disbursement(draft["id"], make_sponsor_admin_headers()))
        assert after["status"] == "DRAFT"

    def test_staff_payee_requires_active_engagement(self, api):
        """PRD §3.4: "A `STAFF` payee must reference a `staff_engagement_id` that
        exists, belongs to this project, and is itself `ACTIVE`, else
        `ERR_STAFF_ENGAGEMENT_REQUIRED`."

        Design: Corner/validations/v_staff_payee_requires_active_engagement
        """
        bundle = create_active_bundle("user_c_v9", project_name="SP", contact_email="sp@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        draft = create_disbursement_draft(pid, 5000, purpose="payroll-ish",
                                          payee_type="STAFF", payee_name="Ghost",
                                          spend_date="2026-06-01")
        resp = api.submit_disbursement(draft["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_STAFF_ENGAGEMENT_REQUIRED)
        after = validate_success(api.get_disbursement(draft["id"], make_sponsor_admin_headers()))
        assert after["status"] == "DRAFT"


class TestCrossEntityStateGates:
    def test_submit_blocked_while_project_suspended(self, api):
        """PRD §3.4: "The project must be `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/disbursement_submit_requires_project_active
        """
        bundle = create_active_bundle("user_app_q", project_name="Rho", contact_email="r@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        draft = create_disbursement_draft(pid, 10000, purpose="printing",
                                          payee_name="PrintCo", spend_date="2026-06-05")
        suspend_project(pid, reason="hold")
        resp = api.submit_disbursement(draft["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACTIVE)

    def test_submit_reenabled_after_reinstate(self, api):
        """PRD §3.4: "The project must be `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE`)"
        PRD §3.6: "Reinstatement belongs to the `SponsorAdmin` alone and moves a
        `SUSPENDED` project back to `ACTIVE`, unfreezing the fund from `FROZEN` to
        `ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/disbursement_submit_requires_project_active
        """
        bundle = create_active_bundle("user_app_q2", project_name="Rho2",
                                      contact_email="r2@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        draft = create_disbursement_draft(pid, 10000, purpose="printing",
                                          payee_name="PrintCo", spend_date="2026-06-05")
        suspend_project(pid, reason="hold")
        validate_error(api.submit_disbursement(draft["id"], make_project_lead_headers(pid)),
                       ApiErrorId.ERR_PROJECT_NOT_ACTIVE)
        reinstate_project(pid)
        submitted = submit_disbursement(draft["id"], pid)
        assert submitted["status"] == "SUBMITTED"

    def test_suspended_submit_surfaces_state_error_not_fiscal(self, api):
        """PRD §2.11: "Seventh, state-machine guards: the target resource must be in a
        from-state of the requested transition" run before the domain sequence in which
        "fund sufficiency (`ERR_INSUFFICIENT_FUNDS`)" appears — PRD §2.11: "the
        relative order is normative because it determines which error surfaces when
        several problems coexist."
        A 150,000 submit on a SUSPENDED project with 92,000 available surfaces
        ERR_PROJECT_NOT_ACTIVE, never ERR_INSUFFICIENT_FUNDS.

        Design: Difficulty/priority_pair_validation_conflict/suspended_state_error_beats_insufficient_funds
        """
        bundle = create_active_bundle("user_app_l", project_name="Mu", contact_email="m@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        suspend_project(pid, reason="audit hold")
        draft = create_disbursement_draft(pid, 150000, purpose="over-balance spend",
                                          payee_name="BigCo", spend_date="2026-06-05")
        resp = api.submit_disbursement(draft["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACTIVE)

    def test_suspended_submit_leaves_no_trace(self, api):
        """PRD §3.4: "A successful submission takes a commitment: the fund's
        `committed_cents` grows by the amount and a `COMMITMENT_HOLD` ledger entry is
        posted with `disbursement_id` set" — a rejected submission is not successful,
        so no commitment exists.

        Design: Difficulty/priority_pair_validation_conflict/suspended_state_error_beats_insufficient_funds
        """
        bundle = create_active_bundle("user_app_l2", project_name="Mu2",
                                      contact_email="m2@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        suspend_project(pid, reason="audit hold")
        draft = create_disbursement_draft(pid, 150000, purpose="over-balance spend",
                                          payee_name="BigCo", spend_date="2026-06-05")
        validate_error(api.submit_disbursement(draft["id"], make_project_lead_headers(pid)),
                       ApiErrorId.ERR_PROJECT_NOT_ACTIVE)
        after = validate_success(api.get_disbursement(draft["id"], make_sponsor_admin_headers()))
        assert after["status"] == "DRAFT"
        assert get_fund(bundle["fund_account_id"])["committed_cents"] == 0


class TestHighValueRoutingAndTerminalStates:
    def test_high_value_routes_through_sponsor(self, api):
        """PRD §3.4: "its `high_value` flag is computed once: true when `amount_cents`
        reaches 1,000,000 cents (ten thousand dollars)."
        PRD §3.4: "An `APPROVE` records `compliance_approved_by_user_id` and routes by
        `high_value`: ordinary requests move `SUBMITTED` to `APPROVED_FOR_PAYMENT`,
        while high-value ones detour to `PENDING_SPONSOR`."
        PRD §3.4: "an `APPROVE` records `sponsor_approved_by_user_id` and moves the
        request to `APPROVED_FOR_PAYMENT`"

        Design: Corner/validations/v_high_value_routes_through_sponsor
        """
        bundle = create_active_bundle("user_c_v18", project_name="HV",
                                      budget_estimate_cents=900000000, contact_email="hv@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 2000000)
        draft = create_disbursement_draft(pid, 1000000, purpose="building",
                                          payee_name="BuildCo", spend_date="2026-06-01")
        assert draft["high_value"] is True, "exactly 1,000,000 reaches the threshold"

        submit_disbursement(draft["id"], pid)
        reviewed = compliance_approve_disbursement(draft["id"])
        assert reviewed["status"] == "PENDING_SPONSOR", "high-value detours to the sponsor"

        early_pay = api.pay_disbursement(draft["id"], make_finance_officer_headers())
        validate_error(early_pay, ApiErrorId.ERR_DISBURSEMENT_STATE_INVALID)

        sponsor_ok = validate_success(api.sponsor_approve_disbursement(
            draft["id"], review_decision_payload(decision="APPROVE"),
            make_sponsor_admin_headers()))
        assert sponsor_ok["status"] == "APPROVED_FOR_PAYMENT"
        paid = pay_disbursement(draft["id"])
        assert paid["status"] == "PAID"

    def test_paid_disbursement_terminal_lockdown(self, api):
        """PRD §3.4: "The request reaches `PAID`, a terminal state alongside `REJECTED`
        and `CANCELLED`."
        PRD §3.4: "Cancellation is the lead's own escape hatch: from `DRAFT` a cancel
        moves straight to `CANCELLED` with no ledger effect, while from `SUBMITTED` it
        additionally releases the commitment."

        Design: Corner/state_machines/sm_paid_disbursement_terminal_lockdown
        """
        bundle = create_active_bundle("user_c_pd", project_name="PD", contact_email="pd@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 500000)
        paid = create_paid_disbursement(pid, 30000, purpose="tools", payee_name="ToolCo")
        assert paid["status"] == "PAID"
        resp = api.cancel_disbursement(paid["id"], make_project_lead_headers(pid))
        validate_error(resp, ApiErrorId.ERR_DISBURSEMENT_STATE_INVALID)
        after = validate_success(api.get_disbursement(paid["id"], make_sponsor_admin_headers()))
        assert after["status"] == "PAID"

    def test_pay_blocked_by_open_critical_incident(self, api):
        """PRD §3.4: "no `CRITICAL` incident may be open on the project in `REPORTED`,
        `TRIAGED`, or `MITIGATING` (`ERR_CRITICAL_INCIDENT_OPEN`)"

        Design: Corner/errors/err_critical_incident_open
        """
        bundle = create_active_bundle("user_c_r2", project_name="CI", contact_email="ci@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 500000)
        approved = create_approved_disbursement(pid, 30000)
        assert approved["status"] == "APPROVED_FOR_PAYMENT"
        report_incident(pid, severity="CRITICAL", category="LIABILITY",
                        description="lawsuit")
        resp = api.pay_disbursement(approved["id"], make_finance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_CRITICAL_INCIDENT_OPEN)
        after = validate_success(api.get_disbursement(approved["id"], make_sponsor_admin_headers()))
        assert after["status"] == "APPROVED_FOR_PAYMENT"
        assert get_fund(bundle["fund_account_id"])["committed_cents"] == 30000


class TestSegregationOfDutiesAndRbac:
    def test_finance_cannot_compliance_review(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /fsa/disbursement-requests/{id}/compliance-review is authorized
        for ComplianceOfficer only.

        Design: Corner/rbac/rbac_finance_cannot_compliance_review
        """
        bundle = create_active_bundle("user_c_b3", project_name="RB3", contact_email="rb3@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        submitted = create_submitted_disbursement(pid, 5000)
        resp = api.compliance_review_disbursement(
            submitted["id"], review_decision_payload(decision="APPROVE"),
            make_finance_officer_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = validate_success(api.get_disbursement(submitted["id"], make_sponsor_admin_headers()))
        assert after["status"] == "SUBMITTED"

    def test_compliance_cannot_pay(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /fsa/disbursement-requests/{id}/pay is authorized for
        FinanceOfficer only.

        Design: Corner/rbac/rbac_compliance_cannot_pay
        """
        bundle = create_active_bundle("user_c_b4", project_name="RB4", contact_email="rb4@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        approved = create_approved_disbursement(pid, 5000)
        resp = api.pay_disbursement(approved["id"], make_compliance_officer_headers("user_co_2"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = validate_success(api.get_disbursement(approved["id"], make_sponsor_admin_headers()))
        assert after["status"] == "APPROVED_FOR_PAYMENT"

    def test_sponsor_admin_cannot_submit_disbursement(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's authorized
        list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST /fsa/disbursement-requests/{id}/submit is authorized for
        ProjectLead only.

        Design: Corner/rbac/rbac_sponsor_admin_cannot_submit_disbursement
        """
        bundle = create_active_bundle("user_c_b6", project_name="RB6", contact_email="rb6@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        draft = create_disbursement_draft(pid, 5000)
        resp = api.submit_disbursement(draft["id"], make_sponsor_admin_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        after = validate_success(api.get_disbursement(draft["id"], make_sponsor_admin_headers()))
        assert after["status"] == "DRAFT"

    def test_sod_compliance_approver_cannot_pay(self, api):
        """PRD §2.9: "The user who submits a request may not compliance-review it;
        sponsor approval of a high-value request requires a user distinct from both the
        submitter and the compliance approver; and payment requires a user distinct
        from the submitter, the compliance approver, and — when one was recorded — the
        sponsor approver."
        PRD §2.9: "Each stage records its actor (`submitted_by_user_id`,
        `compliance_approved_by_user_id`, `sponsor_approved_by_user_id`,
        `paid_by_user_id`), and a violation at any of the three decision points is
        rejected with `ERR_SOD_VIOLATION` (HTTP 403)."
        The payer's user id equals the recorded compliance approver's user id.

        Design: Corner/rbac/sod_compliance_approver_cannot_pay
        """
        bundle = create_active_bundle("user_c_d1", project_name="SD1", contact_email="sd1@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000, finance_id="user_fo_2")
        submitted = create_submitted_disbursement(pid, 5000)
        approved = compliance_approve_disbursement(submitted["id"], officer_id="user_fo_1")
        assert approved["status"] == "APPROVED_FOR_PAYMENT"
        resp = api.pay_disbursement(approved["id"], make_finance_officer_headers("user_fo_1"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        after = validate_success(api.get_disbursement(approved["id"], make_sponsor_admin_headers()))
        assert after["status"] == "APPROVED_FOR_PAYMENT"

    def test_sod_sponsor_approver_must_differ_from_compliance(self, api):
        """PRD §2.9: "sponsor approval of a high-value request requires a user distinct
        from both the submitter and the compliance approver"

        Design: Corner/rbac/sod_sponsor_signer_reused_from_compliance_rejected
        """
        bundle = create_active_bundle("user_c_d2", project_name="SD2",
                                      budget_estimate_cents=900000000, contact_email="sd2@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 2000000)
        submitted = create_submitted_disbursement(pid, 1000000, purpose="big")
        reviewed = compliance_approve_disbursement(submitted["id"], officer_id="user_sa_9")
        assert reviewed["status"] == "PENDING_SPONSOR"
        resp = api.sponsor_approve_disbursement(
            submitted["id"], review_decision_payload(decision="APPROVE"),
            make_sponsor_admin_headers("user_sa_9"))
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        after = validate_success(api.get_disbursement(submitted["id"], make_sponsor_admin_headers()))
        assert after["status"] == "PENDING_SPONSOR"


class TestFundConservation:
    def test_fund_totals_after_commit_pay_cancel(self, api):
        """PRD §3.4: "Payment converts commitment to spend: `committed_cents` falls by
        the amount while `total_disbursed_cents` rises by it"
        PRD §3.4: "The commitment is released on every exit from the pipeline other
        than payment: compliance return, rejection at either gate, cancellation from
        `SUBMITTED`, and the suspension cascade all subtract the amount from
        `committed_cents`, post a `COMMITMENT_RELEASE` entry, and release the tranche
        commitment when one was taken."
        Receipts 100,000 (fee 8,000) + 200,000 (fee 16,000); pay 50,000; cancel 30,000.

        Design: Difficulty/compensating_invariant/fund_conservation_across_commit_pay_cancel
        """
        bundle = create_active_bundle("user_app_v", project_name="Chi", contact_email="ch@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        create_received_donation(pid, 200000)

        dr_a = create_submitted_disbursement(pid, 50000, purpose="A", payee_name="A Co",
                                             spend_date="2026-06-01")
        dr_b = create_submitted_disbursement(pid, 30000, purpose="B", payee_name="B Co",
                                             spend_date="2026-06-02")
        compliance_approve_disbursement(dr_a["id"])
        pay_disbursement(dr_a["id"])
        validate_success(api.cancel_disbursement(dr_b["id"], make_project_lead_headers(pid)))

        fund = get_fund(bundle["fund_account_id"])
        assert fund["available_cents"] == 226000
        assert fund["committed_cents"] == 0
        assert fund["total_received_cents"] == 300000
        assert fund["total_fees_charged_cents"] == 24000
        assert fund["total_disbursed_cents"] == 50000

    def test_fund_conservation_invariant_at_each_step(self, api):
        """PRD §2.6: "after any posting, `available_cents` recomputed from the totals
        must equal its stored value"

        Design: Difficulty/compensating_invariant/fund_conservation_across_commit_pay_cancel
        """
        bundle = create_active_bundle("user_app_v2", project_name="Chi2",
                                      contact_email="ch2@x.org")
        pid = bundle["project_id"]
        fid = bundle["fund_account_id"]
        create_received_donation(pid, 100000)
        create_received_donation(pid, 200000)

        def conserved():
            assert_fund_conservation(get_fund(fid))

        dr_a = create_submitted_disbursement(pid, 50000, purpose="A", payee_name="A Co",
                                             spend_date="2026-06-01")
        fund = get_fund(fid)
        assert fund["committed_cents"] == 50000
        assert fund["available_cents"] == 226000  # 300,000 - 24,000 - 50,000
        conserved()

        dr_b = create_submitted_disbursement(pid, 30000, purpose="B", payee_name="B Co",
                                             spend_date="2026-06-02")
        fund = get_fund(fid)
        assert fund["committed_cents"] == 80000
        assert fund["available_cents"] == 196000
        conserved()

        compliance_approve_disbursement(dr_a["id"])
        pay_disbursement(dr_a["id"])
        fund = get_fund(fid)
        assert fund["committed_cents"] == 30000
        assert fund["total_disbursed_cents"] == 50000
        assert fund["available_cents"] == 196000
        conserved()

        validate_success(api.cancel_disbursement(dr_b["id"], make_project_lead_headers(pid)))
        fund = get_fund(fid)
        assert fund["committed_cents"] == 0
        assert fund["available_cents"] == 226000
        conserved()

    def test_available_excludes_cancelled_and_pledged(self, api):
        """PRD §2.6: "A second derived figure, `forward_available_cents`, adds a pledge
        credit to the settled figure: eighty percent of the sum of `amount_cents` over
        the project's donations still in `PLEDGED`, with the credit rounded half up to
        whole cents once after aggregation."
        PRD §3.4: "from `SUBMITTED` it additionally releases the commitment."
        Settled available stays 92,000 across submit/cancel of 20,000; the 50,000
        PLEDGED gift never enters it.

        Design: Corner/calculations/c_available_excludes_cancelled_and_pledged
        """
        bundle = create_active_bundle("user_c_f4", project_name="F4", contact_email="f4@x.org")
        pid = bundle["project_id"]
        fid = bundle["fund_account_id"]
        create_received_donation(pid, 100000)
        pledge_donation(pid, 50000)  # stays PLEDGED

        submitted = create_submitted_disbursement(pid, 20000)
        fund = get_fund(fid)
        assert fund["available_cents"] == 72000
        assert fund["committed_cents"] == 20000

        validate_success(api.cancel_disbursement(submitted["id"], make_project_lead_headers(pid)))
        fund = get_fund(fid)
        assert fund["available_cents"] == 92000, "cancelled request fully released"
        assert fund["committed_cents"] == 0
        assert fund["forward_available_cents"] == 132000, "92,000 + 0.8 x 50,000 pledged credit"


class TestImmediateConsistency:
    def test_immediate_consistency_on_pay(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data field."
        PRD §3.4: "Payment converts commitment to spend: `committed_cents` falls by the
        amount while `total_disbursed_cents` rises by it"
        Pay response itself reports PAID; an immediate read shows committed 0,
        disbursed 30,000, available 62,000.

        Design: Corner/consistency_model/cm_immediate_consistency_on_pay
        """
        bundle = create_active_bundle("user_c_m1", project_name="CM", contact_email="cm@x.org")
        pid = bundle["project_id"]
        create_received_donation(pid, 100000)
        approved = create_approved_disbursement(pid, 30000)

        paid = pay_disbursement(approved["id"])
        assert paid["status"] == "PAID", "pay response carries the updated resource"

        fund = get_fund(bundle["fund_account_id"])
        assert fund["committed_cents"] == 0
        assert fund["total_disbursed_cents"] == 30000
        assert fund["available_cents"] == 62000
