"""Appeal terminal outcomes: branching side effects, transitive cascades, cross-entity gates,
compensating reversals, filing-deadline boundary, and validation precedence (depth coverage)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_analyst_headers, get_success_data, create_exemption_claim_payload, TEST_USERS,
)
from test_helpers import fixtures as fx

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]

_COMP_30M = [{"comp_address": "x", "sale_price_cents": 30000000,
              "comp_assessed_value_cents": 27000000, "adjustment_pct": 0.00}]


def _filed_then_offer_accepted(api, offer_value_cents, accept_fee=False):
    """Filed appeal (requested 30000000) -> offer created by analyst -> accepted by a second analyst."""
    ctx = fx.setup_filed_appeal(api, valuation_method="SALES_COMPARISON", comps=_COMP_30M,
                                two_analysts=True, accept_fee=accept_fee)
    offer = fx.add_offer(api, ctx["analyst_id"], ctx["appeal_id"], offer_value_cents, proposed_by="JURISDICTION")
    ctx["offer_id"] = offer["id"]
    ctx["accept_resp"] = api.accept_settlement_offer(offer["id"], make_analyst_headers(ctx["analyst2_id"]))
    return ctx


class TestSettledBranchSideEffects:
    """SETTLED branch sets settlement_value_cents + outcome_source=SETTLEMENT (disjoint from DECIDED).
    Design: Difficulty/non_linear_state_machine/ni_appeal_branch_settled_side_effects
    """

    def test_settle_sets_settlement_outcome_fields(self, api):
        """PRD §3.7: "The appeal's `settlement_value_cents` is set to the accepted offer's
        `offer_value_cents`, its `outcome_source` is set to `SETTLEMENT`, and its `realized_savings_cents`
        is computed as the final tax-savings variant over that settlement value."

        Design: Difficulty/non_linear_state_machine/ni_appeal_branch_settled_side_effects
        """
        ctx = _filed_then_offer_accepted(api, 26000000)
        validate_success(ctx["accept_resp"])
        appeal = validate_success(api.get_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"])))
        assert appeal["status"] == "SETTLED"
        assert appeal["outcome_source"] == "SETTLEMENT"
        assert appeal["settlement_value_cents"] == 26000000

    def test_settle_realized_savings_and_assessment_finalized(self, api):
        """PRD §3.7: "the parent assessment advances from `UNDER_APPEAL` to `FINALIZED`, its effective
        `assessed_value_cents` is set to the `settlement_value_cents`". realized = (30000000-26000000)*25/1000
        = 100000.

        Design: Difficulty/non_linear_state_machine/ni_appeal_branch_settled_side_effects
        """
        ctx = _filed_then_offer_accepted(api, 26000000)
        validate_success(ctx["accept_resp"])
        appeal = validate_success(api.get_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"])))
        assert appeal["realized_savings_cents"] == 100000
        assessment = validate_success(api.get_assessment(ctx["assessment_id"], make_analyst_headers(ctx["analyst_id"])))
        assert assessment["status"] == "FINALIZED"
        assert assessment["assessed_value_cents"] == 26000000


class TestSettlementAcceptCascadeDepth3:
    """Accept -> Offer ACCEPTED -> Appeal SETTLED -> Assessment FINALIZED (+ DRAFT invoice).
    Design: Difficulty/transitive_cascade/tc_settlement_accept_chain_depth3
    """

    def test_offer_and_appeal_reach_terminal_states(self, api):
        """PRD §3.7: "Three cascades follow in concert: the accepted offer moves to `ACCEPTED`; the
        parent assessment advances from `UNDER_APPEAL` to `FINALIZED` ... and a draft invoice is created
        for the appeal".

        Design: Difficulty/transitive_cascade/tc_settlement_accept_chain_depth3
        """
        ctx = _filed_then_offer_accepted(api, 26000000, accept_fee=True)
        validate_success(ctx["accept_resp"])
        offer = validate_success(api.get_settlement_offer(ctx["offer_id"], make_analyst_headers(ctx["analyst_id"])))
        assert offer["status"] == "ACCEPTED"
        appeal = validate_success(api.get_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"])))
        assert appeal["status"] == "SETTLED"

    def test_assessment_finalized_and_invoice_created(self, api):
        """PRD §3.7: "a draft invoice is created for the appeal with `gross_savings_cents` copied from
        `realized_savings_cents` and `fee_amount_cents` set to the final contingency fee over those
        savings". gross 100000, fee = 50000*0.40 + 50000*0.33 = 36500.

        Design: Difficulty/transitive_cascade/tc_settlement_accept_chain_depth3
        """
        ctx = _filed_then_offer_accepted(api, 26000000, accept_fee=True)
        validate_success(ctx["accept_resp"])
        assessment = validate_success(api.get_assessment(ctx["assessment_id"], make_analyst_headers(ctx["analyst_id"])))
        assert assessment["status"] == "FINALIZED"
        assert assessment["assessed_value_cents"] == 26000000
        invoice = fx.invoice_for_appeal(api, ctx["appeal_id"])
        assert invoice["gross_savings_cents"] == 100000
        assert invoice["fee_amount_cents"] == 36500


class TestExemptionApproveRecomputeDepth2:
    """Approve exemption -> Assessment totals recompute -> linked Appeal projected bill recompute.
    Design: Difficulty/transitive_cascade/tc_exemption_approve_recompute_depth2
    """

    def _setup(self, api):
        ctx = fx.setup_filed_appeal(api, valuation_method="ASSESSMENT_EQUITY", comps=fx.DUAL_VARIANT_COMPS)
        ex = get_success_data(api.create_exemption_claim(
            create_exemption_claim_payload(ctx["parcel_id"], tax_year=2026,
                                            exemption_type="HOMESTEAD", exemption_value_cents=5000000),
            make_analyst_headers(ctx["analyst_id"])))
        get_success_data(api.submit_exemption_claim(ex["id"], make_analyst_headers(ctx["analyst_id"])))
        validate_success(api.decide_exemption_claim(ex["id"], {"decision": "APPROVE"}, FIRM_ADMIN))
        return ctx

    def test_assessment_totals_recomputed_on_approval(self, api):
        """PRD §3.2: "the matching assessment's `total_approved_exemption_cents` increases by the
        claim's `exemption_value_cents`, its `projected_annual_tax_cents` is recomputed, and its
        `version` is incremented". total 5000000; tax = (30000000-5000000)*25/1000 = 625000.

        Design: Difficulty/transitive_cascade/tc_exemption_approve_recompute_depth2
        """
        ctx = self._setup(api)
        assessment = validate_success(api.get_assessment(ctx["assessment_id"], make_analyst_headers(ctx["analyst_id"])))
        assert assessment["total_approved_exemption_cents"] == 5000000
        assert assessment["projected_annual_tax_cents"] == 625000

    def test_linked_appeal_projected_bill_recomputed(self, api):
        """PRD §3.2: "for any non-terminal appeal on that assessment, the appeal's
        `projected_client_tax_bill_cents` is recomputed and the appeal's `version` is incremented".
        (29000000-5000000)*25/1000 = 600000.

        Design: Difficulty/transitive_cascade/tc_exemption_approve_recompute_depth2
        """
        ctx = self._setup(api)
        appeal = validate_success(api.get_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"])))
        assert appeal["projected_client_tax_bill_cents"] == 600000


class TestFileThenWithdrawPreservesBase:
    """file (NOTICED->UNDER_APPEAL) then withdraw (UNDER_APPEAL->NOTICED) nets zero drift.
    Design: Difficulty/compensating_invariant/cinv_file_then_withdraw_preserves_assessed_base
    """

    def test_withdraw_returns_states(self, api):
        """PRD §3.7: "An analyst may withdraw an appeal that is in any of `FILED`, `INFORMAL_REVIEW`,
        or `HEARING_SCHEDULED`, moving it to `WITHDRAWN`. Withdrawal is a compensating reversal: the
        parent assessment is returned from `UNDER_APPEAL` back to `NOTICED`".

        Design: Difficulty/compensating_invariant/cinv_file_then_withdraw_preserves_assessed_base
        """
        ctx = fx.setup_filed_appeal(api, comps=_COMP_30M)
        appeal = validate_success(api.withdraw_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"])))
        assert appeal["status"] == "WITHDRAWN"
        assessment = validate_success(api.get_assessment(ctx["assessment_id"], make_analyst_headers(ctx["analyst_id"])))
        assert assessment["status"] == "NOTICED"

    def test_withdraw_leaves_assessed_base_unchanged(self, api):
        """PRD §3.7: "its effective `assessed_value_cents` is left unchanged, still equal to
        `original_assessed_value_cents`, so that a file-then-withdraw sequence provably leaves the
        assessed base exactly as it began."

        Design: Difficulty/compensating_invariant/cinv_file_then_withdraw_preserves_assessed_base
        """
        ctx = fx.setup_filed_appeal(api, comps=_COMP_30M)
        validate_success(api.withdraw_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"])))
        assessment = validate_success(api.get_assessment(ctx["assessment_id"], make_analyst_headers(ctx["analyst_id"])))
        assert assessment["assessed_value_cents"] == 30000000


class TestFilingDeadlineInclusiveBoundary:
    """notice 2026-06-15 + 60 days = 2026-08-14 (inclusive last day).
    Design: Difficulty/boundary_precision_check/bp_filing_deadline_inclusive_last_day
    """

    def _draft_appeal_with_evidence(self, api):
        ctx = fx.setup_base(api)
        appeal = fx.new_appeal(api, ctx["analyst_id"], ctx["assessment_id"], ctx["fee_agreement_id"],
                               "SALES_COMPARISON")
        ctx["appeal_id"] = appeal["id"]
        fx.add_evidence(api, ctx["analyst_id"], appeal["id"], sale_price_cents=27000000,
                        comp_assessed_value_cents=27000000)
        return ctx

    def test_file_on_last_day_succeeds(self, api):
        """PRD §3.4: "filing is allowed only while the current logical-clock date is on or before the
        assessment's `notice_date` advanced by the jurisdiction's `filing_window_days`, with the final
        day included".

        Design: Difficulty/boundary_precision_check/bp_filing_deadline_inclusive_last_day
        """
        ctx = self._draft_appeal_with_evidence(api)
        fx.set_clock(api, "2026-08-14T12:00:00Z")
        appeal = validate_success(api.file_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"])))
        assert appeal["status"] == "FILED"
        assessment = validate_success(api.get_assessment(ctx["assessment_id"], make_analyst_headers(ctx["analyst_id"])))
        assert assessment["status"] == "UNDER_APPEAL"

    def test_file_one_day_past_deadline_rejected(self, api):
        """PRD §3.4: "a date past that boundary is rejected with `ERR_FILING_DEADLINE_PASSED`."

        Design: Difficulty/boundary_precision_check/bp_filing_deadline_inclusive_last_day
        """
        ctx = self._draft_appeal_with_evidence(api)
        fx.set_clock(api, "2026-08-15T00:00:00Z")
        resp = api.file_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"]))
        validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_PASSED.value)


class TestFileBlockedByFinalizedAssessment:
    """A fresh appeal on an already-FINALIZED assessment cannot be filed.
    Design: Difficulty/cross_entity_state_dependency/ce_file_blocked_by_finalized_assessment
    """

    def _setup_second_appeal(self, api):
        ctx = fx.setup_decided_appeal(api, decision_value_cents=27000000, comps=_COMP_30M)
        appeal_b = fx.new_appeal(api, ctx["analyst_id"], ctx["assessment_id"], ctx["fee_agreement_id"],
                                 "SALES_COMPARISON")
        ctx["appeal_b_id"] = appeal_b["id"]
        fx.add_evidence(api, ctx["analyst_id"], appeal_b["id"], comp_address="y",
                        sale_price_cents=26000000, comp_assessed_value_cents=26000000)
        return ctx

    def test_file_on_finalized_assessment_rejected(self, api):
        """PRD §3.4: "the parent assessment must be in `NOTICED` — if it is already `UNDER_APPEAL` or
        `FINALIZED` the filing is rejected with `ERR_ASSESSMENT_NOT_APPEALABLE`."

        Design: Difficulty/cross_entity_state_dependency/ce_file_blocked_by_finalized_assessment
        """
        ctx = self._setup_second_appeal(api)
        assessment = validate_success(api.get_assessment(ctx["assessment_id"], make_analyst_headers(ctx["analyst_id"])))
        assert assessment["status"] == "FINALIZED"
        resp = api.file_appeal(ctx["appeal_b_id"], make_analyst_headers(ctx["analyst_id"]))
        validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_APPEALABLE.value)

    def test_blocked_appeal_stays_draft(self, api):
        """PRD §3.4: "Filing advances the appeal from `DRAFT` to `FILED`". A rejected filing leaves the
        appeal in `DRAFT`.

        Design: Difficulty/cross_entity_state_dependency/ce_file_blocked_by_finalized_assessment
        """
        ctx = self._setup_second_appeal(api)
        api.file_appeal(ctx["appeal_b_id"], make_analyst_headers(ctx["analyst_id"]))
        appeal_b = validate_success(api.get_appeal(ctx["appeal_b_id"], make_analyst_headers(ctx["analyst_id"])))
        assert appeal_b["status"] == "DRAFT"


class TestRecordDecisionBlockedNoHeldHearing:
    """record-decision requires a HELD hearing; a merely SCHEDULED hearing is not enough.
    Design: Difficulty/cross_entity_state_dependency/ce_record_decision_blocked_no_held_hearing
    """

    def _setup(self, api):
        ctx = fx.setup_filed_appeal(api, comps=_COMP_30M, two_analysts=True)
        hearing = fx.schedule_hearing(api, ctx["analyst_id"], ctx["appeal_id"], ctx["analyst2_id"],
                                      "2026-08-01T09:00:00Z", "2026-08-01T10:00:00Z")
        ctx["hearing_id"] = hearing["id"]
        return ctx

    def test_record_decision_without_held_hearing_rejected(self, api):
        """PRD §3.7: "at least one hearing on the appeal must be in `HELD` status, or the request is
        rejected with `ERR_NO_HELD_HEARING`".

        Design: Difficulty/cross_entity_state_dependency/ce_record_decision_blocked_no_held_hearing
        """
        ctx = self._setup(api)
        resp = api.record_decision(ctx["appeal_id"], {"decision_value_cents": 27000000},
                                   make_analyst_headers(ctx["analyst_id"]))
        validate_error(resp, ApiErrorId.ERR_NO_HELD_HEARING.value)

    def test_appeal_stays_hearing_scheduled(self, api):
        """PRD §3.7: "an analyst records the tribunal's decision, moving the appeal from
        `HEARING_SCHEDULED` to `DECIDED`". A rejected decision leaves the appeal in `HEARING_SCHEDULED`.

        Design: Difficulty/cross_entity_state_dependency/ce_record_decision_blocked_no_held_hearing
        """
        ctx = self._setup(api)
        api.record_decision(ctx["appeal_id"], {"decision_value_cents": 27000000},
                            make_analyst_headers(ctx["analyst_id"]))
        appeal = validate_success(api.get_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"])))
        assert appeal["status"] == "HEARING_SCHEDULED"
        hearing = validate_success(api.get_hearing(ctx["hearing_id"], make_analyst_headers(ctx["analyst_id"])))
        assert hearing["status"] == "SCHEDULED"


class TestFilingDeadlineBeatsNoEvidence:
    """Past-deadline AND no-evidence file -> ERR_FILING_DEADLINE_PASSED (window checked before evidence).
    Design: Difficulty/priority_pair_validation_conflict/pp_deadline_temporal_beats_no_evidence_constraint
    """

    def _setup_draft_no_evidence_past_deadline(self, api):
        ctx = fx.setup_base(api)
        appeal = fx.new_appeal(api, ctx["analyst_id"], ctx["assessment_id"], ctx["fee_agreement_id"],
                               "SALES_COMPARISON")
        ctx["appeal_id"] = appeal["id"]
        fx.set_clock(api, "2026-09-01T00:00:00Z")  # deadline was 2026-08-14
        return ctx

    def test_deadline_error_preempts_no_evidence_error(self, api):
        """PRD §3.4: "a date past that boundary is rejected with `ERR_FILING_DEADLINE_PASSED`. Finally,
        at least one included evidence row must exist for the appeal, or the filing is rejected with
        `ERR_NO_EVIDENCE`." The window check is ordered before the evidence check.

        Design: Difficulty/priority_pair_validation_conflict/pp_deadline_temporal_beats_no_evidence_constraint
        """
        ctx = self._setup_draft_no_evidence_past_deadline(api)
        resp = api.file_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"]))
        validate_error(resp, ApiErrorId.ERR_FILING_DEADLINE_PASSED.value)

    def test_appeal_not_filed_after_rejection(self, api):
        """PRD §3.4: "Filing advances the appeal from `DRAFT` to `FILED`". A rejected filing leaves the
        appeal in `DRAFT` with no cascade to the assessment.

        Design: Difficulty/priority_pair_validation_conflict/pp_deadline_temporal_beats_no_evidence_constraint
        """
        ctx = self._setup_draft_no_evidence_past_deadline(api)
        api.file_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"]))
        appeal = validate_success(api.get_appeal(ctx["appeal_id"], make_analyst_headers(ctx["analyst_id"])))
        assert appeal["status"] == "DRAFT"
        assessment = validate_success(api.get_assessment(ctx["assessment_id"], make_analyst_headers(ctx["analyst_id"])))
        assert assessment["status"] == "NOTICED"
