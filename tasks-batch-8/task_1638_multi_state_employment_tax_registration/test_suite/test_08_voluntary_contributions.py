"""Voluntary contributions: projection math, SoD, posture gate, deadline boundary,
declined-state lockout, and the PROPOSED auto-expiry sweep."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_vc,
    create_penalty_notice,
    create_voluntary_contribution_payload,
    get_employer,
    get_success_data,
    make_payroll_compliance_lead_headers,
    make_tax_director_headers,
    make_ui_specialist_headers,
    propose_vc,
    remit_vc,
    set_clock,
    setup_ui_rate_effective,
    validate_error,
    validate_success,
)


class TestVCProjectionCircularOrder:
    def test_vc_projection_rates_without_and_with(self, api):
        """PRD §3.7: "Creation computes a three-part projection in pinned order. First
        `projected_rate_without_vc_bp` is the rate as it stands. Then
        `projected_rate_with_vc_bp` recomputes the experience rate with
        `voluntary_contribution_applied_cents` increased by the proposed amount — the
        proposal itself shifts the reserve ratio that selects the bracket that
        determines the saving."

        Design: Difficulty/combinatorial_formula/vc_optimization_circular_order
        """
        out = setup_ui_rate_effective(account_number="PA-UI-0003")
        vc = propose_vc(out["ui_rate"]["id"], proposed_amount_cents=100_000,
                        decision_deadline="2026-09-01T00:00:00Z")
        assert vc["projected_rate_without_vc_bp"] == 390
        assert vc["projected_rate_with_vc_bp"] == 270, (
            "the 100,000-cent proposal lifts reserve 400 -> 500, crossing the bracket"
        )

    def test_vc_projection_net_savings_200000(self, api):
        """PRD §3.7: "Projected taxable wages sum, over every employee with at least
        one attributed day in the registration's state during `rate_year`, the lesser
        of the employee's `annual_wage_cents` and the agency's `ui_wage_base_cents`.
        Finally `projected_net_savings_cents` is the rate difference — the
        without-projection minus the with-projection, in basis points — multiplied by
        those projected taxable wages and divided by ten thousand, the product rounded
        half up to cents, minus the proposed contribution."

        Design: Difficulty/combinatorial_formula/vc_optimization_circular_order
        """
        out = setup_ui_rate_effective(account_number="PA-UI-0003")
        vc = propose_vc(out["ui_rate"]["id"], proposed_amount_cents=100_000,
                        decision_deadline="2026-09-01T00:00:00Z")
        # 5 employees x min(6,000,000, 5,000,000) = 25,000,000 taxable;
        # (390 - 270) * 25,000,000 / 10,000 - 100,000 = 300,000 - 100,000.
        assert vc["projected_net_savings_cents"] == 200_000

    def test_vc_no_net_savings_rejected(self, api):
        """PRD §3.7: "Only a strictly positive projection survives; anything else is
        rejected with `ERR_NO_NET_SAVINGS`."

        Design: Corner/validations/vc_no_net_savings_rejected
        """
        out = setup_ui_rate_effective(
            account_number="PA-UI-0010",
            employee_wages=(3_000_000,),
            rate_overrides={
                "assigned_rate_bp": 90,
                "contributions_paid_3yr_cents": 1_700_000,
                "benefits_charged_3yr_cents": 200_000,
                "taxable_payroll_3yr_cents": 10_000_000,
            },
        )
        rate = out["ui_rate"]
        assert rate["final_rate_bp"] == 80, (
            "reserve 1500bp -> bracket 50, + 30 surcharge; buy-down stays in bracket"
        )
        res = api.create_voluntary_contribution(
            create_voluntary_contribution_payload(
                rate["id"], proposed_amount_cents=100_000,
                decision_deadline="2026-12-01T00:00:00Z",
            ),
            make_ui_specialist_headers("uis-1"),
        )
        validate_error(res, ApiErrorId.ERR_NO_NET_SAVINGS)


class TestVCSegregationOfDuties:
    def test_vc_self_approval_same_user_rejected(self, api):
        """PRD §3.7: "Approval belongs to the `TaxDirector` and is double-gated: the
        Employer's `compliance_posture` must not be `DELINQUENT` (else
        `ERR_COMPANY_POSTURE_DELINQUENT`), and the approver must differ from
        `proposed_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`); approval records
        `approved_by_user_id`."

        Design: Corner/rbac/vc_self_approval_same_user_rejected
        """
        out = setup_ui_rate_effective(account_number="PA-UI-0011")
        vc = propose_vc(out["ui_rate"]["id"], proposed_amount_cents=100_000,
                        decision_deadline="2026-12-01T00:00:00Z", user_id="uis-1")
        # Same X-User-ID acting under the (valid) TaxDirector role still fails SoD.
        res = api.approve_voluntary_contribution(
            vc["id"], make_tax_director_headers("uis-1")
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        approved = validate_success(
            api.approve_voluntary_contribution(
                vc["id"], make_tax_director_headers("dir-1")
            ),
            200,
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "dir-1"


class TestVCApprovePostureGate:
    def _setup_vc_with_escalated_notice(self):
        out = setup_ui_rate_effective(account_number="PA-UI-0006")
        vc = propose_vc(out["ui_rate"]["id"], proposed_amount_cents=100_000,
                        decision_deadline="2026-12-01T00:00:00Z", user_id="uis-1")
        notice = create_penalty_notice(
            600_000, registration_id=out["registration"]["id"], user_id="pcl-1",
        )
        pcl = make_payroll_compliance_lead_headers("pcl-1")
        return out, vc, notice, pcl

    def test_vc_approve_blocked_by_delinquent_posture(self, api):
        """PRD §2.7: "The posture is `DELINQUENT` when any open notice is `ESCALATED`,
        or any FilingObligation is `LATE` with `late_days` greater than 30, or
        `outstanding_penalty_cents` exceeds 1,000,000 cents (ten thousand dollars)."
        PRD §3.7: "the Employer's `compliance_posture` must not be `DELINQUENT` (else
        `ERR_COMPANY_POSTURE_DELINQUENT`)"

        Design: Difficulty/cross_entity_state_dependency/vc_approve_blocked_by_delinquent_posture
        """
        out, vc, notice, pcl = self._setup_vc_with_escalated_notice()
        get_success_data(api.triage_notice(notice["id"], pcl))
        get_success_data(api.escalate_notice(notice["id"], pcl))
        employer = get_employer(out["employer"]["id"])
        assert employer["compliance_posture"] == "DELINQUENT"
        res = api.approve_voluntary_contribution(
            vc["id"], make_tax_director_headers("dir-1")
        )
        validate_error(res, ApiErrorId.ERR_COMPANY_POSTURE_DELINQUENT)

    def test_vc_approve_after_notice_resolved_succeeds(self, api):
        """PRD §3.7: "Approval belongs to the `TaxDirector` and is double-gated: the
        Employer's `compliance_posture` must not be `DELINQUENT` (else
        `ERR_COMPANY_POSTURE_DELINQUENT`), and the approver must differ from
        `proposed_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`); approval records
        `approved_by_user_id`."

        Design: Difficulty/cross_entity_state_dependency/vc_approve_blocked_by_delinquent_posture
        """
        out, vc, notice, pcl = self._setup_vc_with_escalated_notice()
        get_success_data(api.triage_notice(notice["id"], pcl))
        get_success_data(api.escalate_notice(notice["id"], pcl))
        err = api.approve_voluntary_contribution(
            vc["id"], make_tax_director_headers("dir-1")
        )
        validate_error(err, ApiErrorId.ERR_COMPANY_POSTURE_DELINQUENT)
        resolved = validate_success(
            api.resolve_notice(notice["id"], {"resolution_notes": "Paid in full"}, pcl),
            200,
        )
        assert resolved["status"] == "RESOLVED"
        approved = validate_success(
            api.approve_voluntary_contribution(
                vc["id"], make_tax_director_headers("dir-1")
            ),
            200,
        )
        assert approved["status"] == "APPROVED"


class TestVCRemitDeadlineBoundary:
    def _setup_two_approved_vcs(self):
        out = setup_ui_rate_effective(account_number="PA-UI-0005")
        vc1 = propose_vc(out["ui_rate"]["id"], proposed_amount_cents=100_000,
                         decision_deadline="2026-09-01T17:00:00Z", user_id="uis-1")
        vc2 = propose_vc(out["ui_rate"]["id"], proposed_amount_cents=100_000,
                         decision_deadline="2026-09-01T17:00:00Z", user_id="uis-1")
        approve_vc(vc1["id"], user_id="dir-1")
        approve_vc(vc2["id"], user_id="dir-1")
        return vc1, vc2

    def test_vc_remit_at_exact_deadline_succeeds(self, api):
        """PRD §3.7: "Once `APPROVED`, a `UISpecialist` records remittance to the
        agency — allowed only while the clock has not passed `decision_deadline`; the
        exact deadline instant is permitted, and any later attempt is
        `ERR_DEADLINE_PASSED` — stamping `remitted_at` and landing in `REMITTED`."

        Design: Difficulty/boundary_precision_check/vc_remit_deadline_exact_instant
        """
        vc1, _vc2 = self._setup_two_approved_vcs()
        set_clock("2026-09-01T17:00:00Z")
        res = api.remit_voluntary_contribution(
            vc1["id"], make_ui_specialist_headers("uis-1")
        )
        remitted = validate_success(res, 200)
        assert remitted["status"] == "REMITTED", (
            "the deadline instant itself is permitted (clock <= decision_deadline)"
        )
        assert remitted["remitted_at"] == "2026-09-01T17:00:00Z"

    def test_vc_remit_one_second_past_deadline_rejected(self, api):
        """PRD §3.7: "allowed only while the clock has not passed `decision_deadline`;
        the exact deadline instant is permitted, and any later attempt is
        `ERR_DEADLINE_PASSED`"

        Design: Difficulty/boundary_precision_check/vc_remit_deadline_exact_instant
        """
        vc1, vc2 = self._setup_two_approved_vcs()
        set_clock("2026-09-01T17:00:00Z")
        remit_vc(vc1["id"])
        set_clock("2026-09-01T17:00:01Z")
        res = api.remit_voluntary_contribution(
            vc2["id"], make_ui_specialist_headers("uis-1")
        )
        validate_error(res, ApiErrorId.ERR_DEADLINE_PASSED)


class TestRemitDeclinedStatePriority:
    def _setup_declined_vc(self):
        out = setup_ui_rate_effective(account_number="PA-UI-0004")
        vc = propose_vc(out["ui_rate"]["id"], proposed_amount_cents=100_000,
                        decision_deadline="2026-09-01T00:00:00Z", user_id="uis-1")
        declined = validate_success(
            api_client.decline_voluntary_contribution(
                vc["id"], make_tax_director_headers("dir-1")
            ),
            200,
        )
        assert declined["status"] == "DECLINED"
        return vc

    def test_remit_declined_vc_state_error_beats_deadline(self, api):
        """PRD §2.9: "When several checks could reject the same request, the server
        evaluates them in a fixed order and reports the first failure."
        PRD §2.9: "6. **From-state legality.** The target resource is in a state from
        which the requested transition is allowed (terminal states are locked down, and
        a voluntary contribution may be created only against an `EFFECTIVE` rate), else
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."
        PRD §2.9: "12. **Temporal windows.** Remittance after the decision deadline
        (`ERR_DEADLINE_PASSED`, HTTP 409)"

        Design: Difficulty/priority_pair_validation_conflict/remit_declined_vc_state_beats_deadline
        """
        vc = self._setup_declined_vc()
        set_clock("2026-09-02T00:00:00Z")
        # The DECLINED (terminal) state fails tier 6; the passed deadline would also
        # fail tier 12 — the from-state failure must be reported.
        res = api.remit_voluntary_contribution(
            vc["id"], make_ui_specialist_headers("uis-1")
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    def test_remit_declined_vc_within_deadline_also_state_error(self, api):
        """PRD §3.7: "A director may instead decline, moving `PROPOSED` or `APPROVED`
        to terminal `DECLINED`."
        PRD §2.9: "The target resource is in a state from which the requested
        transition is allowed (terminal states are locked down, and a voluntary
        contribution may be created only against an `EFFECTIVE` rate), else
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/remit_declined_vc_state_beats_deadline
        """
        vc = self._setup_declined_vc()
        # Clock is still 2026-08-20 (within the 2026-09-01 deadline): only the
        # from-state check can fire, isolating the DECLINED lockout.
        res = api.remit_voluntary_contribution(
            vc["id"], make_ui_specialist_headers("uis-1")
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


class TestVCProposedSweepExpiry:
    def test_scheduled_vc_proposed_expires_on_sweep(self, api, tax_director_headers):
        """PRD §3.7: "Only `PROPOSED` rows auto-expire: the sweep moves a `PROPOSED`
        contribution whose `decision_deadline` has passed to terminal `EXPIRED`."

        Design: Corner/cross_cutting_layers/scheduled_vc_proposed_expires_on_sweep
        """
        out = setup_ui_rate_effective(account_number="PA-UI-0013")
        vc = propose_vc(out["ui_rate"]["id"], proposed_amount_cents=100_000,
                        decision_deadline="2026-09-01T00:00:00Z", user_id="uis-1")
        assert vc["status"] == "PROPOSED"
        set_clock("2026-09-02T00:00:00Z")
        after = get_success_data(
            api.get_voluntary_contribution(vc["id"], tax_director_headers)
        )
        assert after["status"] == "EXPIRED"
