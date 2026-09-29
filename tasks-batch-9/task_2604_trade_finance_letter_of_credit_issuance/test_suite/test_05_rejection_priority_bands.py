"""Two requests that violate two rules at once, in two different error-category pairs.

An issuance blocked by both its state and the facility's headroom must answer on the state
band, and a claim blocked by both a sanctions block and an incoherent claim form must
answer on the compliance-safety band. In both pairs the loser is a real violation that
surfaces only once the winner is repaired.
"""

from prd_bench_local_runner.testing import validate_error
from test_helpers import (
    api_client,
    approve_credit,
    assert_facility_ledger,
    assert_screening_outcome,
    conclude_examination,
    draft_credit,
    factories,
    issued_credit,
    newest_presentation_screening,
    rescreen_presentation,
    review_screening,
    set_clock,
    setup_parties,
    submit_credit_for_approval,
    submitted_presentation,
    trade_finance_officer_headers,
    COMPLIANCE_OFFICER_1,
    COMPLIANCE_OFFICER_2,
)

OVER_LIMIT_TERMS = {
    "amount_cents": 20000000,
    "available_by": "SIGHT_PAYMENT",
    "tenor_days": 0,
    "tolerance_pct": 0,
    "latest_shipment_date": "2026-09-15",
    "expiry_date": "2026-10-05",
    "presentation_period_days": 21,
}


class TestStateBandOutranksFiscalBandOnIssuance:
    """A 20,000,000 credit still in `DRAFT` against a 5,000,000 facility."""

    def _draft_over_limit(self):
        parties = setup_parties(facility={"limit_cents": 5000000})
        return draft_credit(parties, None, **OVER_LIMIT_TERMS)

    def _attempt_issue(self, credit_id):
        return api_client.issue_credit(
            credit_id, factories.issue_payload(), trade_finance_officer_headers()
        )

    def test_a_draft_credit_over_its_facility_headroom_answers_on_the_state_band(self, clock):
        """Both violations are live, and the 409 wins over the 422.

        PRD 2.9: "An issuance attempt on a credit that is still in `DRAFT` and whose
        committed allocation would also exceed the facility's headroom returns
        `ERR_CREDIT_NOT_APPROVED` (409) — the state band outranks the fiscal band — and not
        `ERR_FACILITY_LIMIT_EXCEEDED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_priority4_beats_fiscal_priority26_on_unapproved_over_limit_issue
        """
        ctx = self._draft_over_limit()
        assert ctx.credit["status"] == "DRAFT"

        response = self._attempt_issue(ctx.credit_id)

        validate_error(response, "ERR_CREDIT_NOT_APPROVED", 409)
        assert response.json()["data"]["error_id"] != "ERR_FACILITY_LIMIT_EXCEEDED"

    def test_the_fiscal_violation_surfaces_only_after_the_state_is_repaired(self, clock):
        """Approving the credit removes the state violation and exposes the headroom breach.

        PRD 2.9: "Fiscal capacity comes last precisely because a facility breach is a
        curable commercial condition while a sanctions hit is not."

        Design: Difficulty/priority_pair_validation_conflict/state_priority4_beats_fiscal_priority26_on_unapproved_over_limit_issue
        """
        ctx = self._draft_over_limit()
        validate_error(self._attempt_issue(ctx.credit_id), "ERR_CREDIT_NOT_APPROVED", 409)
        submit_credit_for_approval(ctx.credit_id)
        approve_credit(ctx.credit_id)

        response = self._attempt_issue(ctx.credit_id)

        validate_error(response, "ERR_FACILITY_LIMIT_EXCEEDED", 422)
        assert ctx.refresh()["status"] == "APPROVED"

    def test_neither_rejected_issuance_commits_anything(self, clock):
        """Two refused issuances leave the credit and the facility exactly as they were.

        PRD 2.9: "When one request violates several rules, exactly one error is returned,
        and which one is not a matter of implementation convenience."

        Design: Difficulty/priority_pair_validation_conflict/state_priority4_beats_fiscal_priority26_on_unapproved_over_limit_issue
        """
        ctx = self._draft_over_limit()
        validate_error(self._attempt_issue(ctx.credit_id), "ERR_CREDIT_NOT_APPROVED", 409)
        submit_credit_for_approval(ctx.credit_id)
        approve_credit(ctx.credit_id)
        validate_error(self._attempt_issue(ctx.credit_id), "ERR_FACILITY_LIMIT_EXCEEDED", 422)

        assert ctx.refresh()["committed_allocation_cents"] == 0
        assert_facility_ledger(
            ctx.refresh_facility(),
            allocated_cents=0,
            available_cents=5000000,
            status="ACTIVE",
        )


class TestComplianceSafetyBandOutranksReferentialBandOnClaims:
    """A negotiation claim on a sight credit whose documents have just been blocked."""

    def _blocked_but_complying_file(self):
        ctx = issued_credit(
            setup_parties(facility={"limit_cents": 50000000}),
            amount_cents=5000000,
            available_by="SIGHT_PAYMENT",
            tenor_days=0,
            tolerance_pct=0,
            latest_shipment_date="2026-10-31",
            expiry_date="2026-11-30",
            presentation_period_days=21,
        )
        set_clock("2026-09-14T09:00:00Z")
        pctx = submitted_presentation(
            ctx,
            (2000000,),
            invoice_overrides={
                "goods_description": "Rack mount servers",
                "hs_code": "8471600000",
                "consignee_country": "PL",
                "transit_country_codes": ["SG"],
            },
            transport_overrides={
                "goods_description": "Rack mount servers",
                "consignee_country": "PL",
                "transit_country_codes": ["SG"],
            },
        )
        first_check = newest_presentation_screening(pctx.presentation_id)
        review_screening(first_check["id"], "RELEASE", COMPLIANCE_OFFICER_1)
        conclude_examination(pctx)
        second_check = rescreen_presentation(
            pctx, "PRESENTED_DOCUMENTS", COMPLIANCE_OFFICER_1
        )
        review_screening(second_check["id"], "BLOCK", COMPLIANCE_OFFICER_2)
        pctx.refresh()
        return pctx, first_check, second_check

    def _attempt_claim(self, pctx):
        return api_client.create_settlement_claim(
            pctx.presentation_id,
            factories.settlement_claim_payload("NEGOTIATION", 2000000),
            pctx.bank_headers,
        )

    def test_one_dual_use_tariff_prefix_scores_sixty_and_reviews(self, clock):
        """A single 8471 invoice scores 60, which reviews rather than blocks by itself.

        PRD 3.8: "`risk_score` is 100 per country hit, plus 60 per dual-use hit, plus 40 per
        keyword hit, plus 20 per transit hit, and the total is then capped at 200 — a score
        never exceeds 200 however many hits accumulate."

        Design: Difficulty/priority_pair_validation_conflict/safety_priority20_beats_referential_priority24_on_blocked_screening_claim
        """
        pctx, first_check, second_check = self._blocked_but_complying_file()

        assert first_check["dual_use_hits"] == 1
        assert first_check["risk_score"] == 60
        assert_screening_outcome(
            newest_presentation_screening(pctx.presentation_id),
            result="BLOCKED",
            risk_score=60,
        )
        assert second_check["id"] != first_check["id"]

    def test_the_sanctions_block_answers_before_the_claim_type_incoherence(self, clock):
        """`NEGOTIATION` on a sight credit is also wrong, and the 403 still wins.

        PRD 2.9: "A settlement claim lodged on a presentation whose documents screened
        `BLOCKED`, sent with a claim form the credit's availability does not admit, returns
        `ERR_SANCTIONS_BLOCK` (403) and not `ERR_CLAIM_TYPE_MISMATCH` (422)."

        Design: Difficulty/priority_pair_validation_conflict/safety_priority20_beats_referential_priority24_on_blocked_screening_claim
        """
        pctx, _first, _second = self._blocked_but_complying_file()

        response = self._attempt_claim(pctx)

        validate_error(response, "ERR_SANCTIONS_BLOCK", 403)
        assert response.status_code != 422
        assert response.json()["data"]["error_id"] != "ERR_CLAIM_TYPE_MISMATCH"

    def test_the_refused_claim_leaves_both_presentation_dimensions_alone(self, clock):
        """The examination verdict and the frozen drawing survive the refused claim.

        PRD 3.8: "Settlement proceeds only when the newest check is `CLEAR` or `RELEASED`."

        Design: Difficulty/priority_pair_validation_conflict/safety_priority20_beats_referential_priority24_on_blocked_screening_claim
        """
        pctx, _first, _second = self._blocked_but_complying_file()

        self._attempt_claim(pctx)

        presentation = pctx.refresh()
        assert presentation["examination_status"] == "COMPLYING"
        assert presentation["settlement_status"] == "UNSETTLED"
        assert presentation["drawn_amount_cents"] == 2000000
