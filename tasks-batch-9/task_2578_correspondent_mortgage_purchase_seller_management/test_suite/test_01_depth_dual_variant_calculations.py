"""Dual-variant money and rate calculations: the same inputs, two formulas."""

from test_helpers import (
    ANALYST,
    TRADER,
    api_client,
    assert_commitment,
    assert_seller_scorecard,
    fixtures,
    validate_success,
)


class TestPairOffFeeDualVariant:
    """Mark-to-market versus administrative-only pair-off pricing."""

    @staticmethod
    def _two_lines_ready_to_pair_off() -> dict:
        """An approved seller holding one mandatory and one best-efforts line."""
        staged = fixtures.setup_locked_commitment(
            commitment_overrides={"commitment_type": "MANDATORY"}
        )
        best_efforts = fixtures.setup_commitment(
            staged["seller_id"],
            staged["product_id"],
            commitment_type="BEST_EFFORTS",
        )
        staged["best_efforts"] = best_efforts
        return staged

    def test_mandatory_pair_off_assesses_market_loss_plus_administrative_fee(self):
        """A mandatory line paired off below its locked price takes market loss.

        Notional 100,000,000 with tolerance 2,000,000 leaves 98,000,000 billable;
        the locked price 100.880 exceeds the observed market price 100.500 by
        0.380, so the market loss is 372,400 cents and the total fee is 397,400
        once the flat administrative component is added.

        PRD: "The market loss is the billable amount multiplied by the excess of
        the locked `commitment_price_pct` over the observed
        `pair_off_market_price_pct`, that excess floored at zero, the product
        divided by 100, and the result rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/pair_off_fee_mandatory_mark_to_market_vs_best_efforts_admin_only
        """
        staged = self._two_lines_ready_to_pair_off()
        mandatory_id = staged["commitment_id"]

        assert staged["commitment"]["commitment_price_pct"] == 100.880
        assert staged["commitment"]["tolerance_cents"] == 2000000

        response = api_client.pair_off_commitment(
            mandatory_id, {"pair_off_market_price_pct": 100.500}, TRADER
        )
        paired = validate_success(response, 200)

        assert_commitment(paired)
        assert paired["status"] == "PAIRED_OFF"
        assert paired["pair_off_method"] == "MANDATORY_MARK_TO_MARKET"
        assert paired["pair_off_fee_cents"] == 397400
        assert paired["pair_off_market_price_pct"] == 100.500
        assert paired["paired_off_amount_cents"] == 100000000
        assert paired["available_amount_cents"] == 0

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["fee_receivable_cents"] == 397400
        assert seller["open_mandatory_exposure_cents"] == 0

    def test_best_efforts_pair_off_charges_the_flat_fee_alone(self):
        """The best-efforts variant omits mark-to-market entirely.

        Both lines carry notional 100,000,000, both are untouched, and both are
        paired off at the identical market price 100.500. The mandatory line is
        charged 397,400 and the best-efforts line only the flat 25,000 — a
        372,400-cent divergence driven solely by `commitment_type`. The seller's
        receivable accumulates both fees, 422,400 in total.

        PRD: "The fee is the administrative component alone; no mark-to-market
        element is assessed."

        Design: Difficulty/dual_variant_calc/pair_off_fee_mandatory_mark_to_market_vs_best_efforts_admin_only
        """
        staged = self._two_lines_ready_to_pair_off()
        best_efforts = staged["best_efforts"]

        assert best_efforts["commitment_price_pct"] == 100.280
        assert best_efforts["tolerance_cents"] == 2000000

        mandatory_paired = validate_success(
            api_client.pair_off_commitment(
                staged["commitment_id"], {"pair_off_market_price_pct": 100.500}, TRADER
            ),
            200,
        )
        best_efforts_paired = validate_success(
            api_client.pair_off_commitment(
                best_efforts["id"], {"pair_off_market_price_pct": 100.500}, TRADER
            ),
            200,
        )

        assert_commitment(best_efforts_paired)
        assert best_efforts_paired["status"] == "PAIRED_OFF"
        assert best_efforts_paired["pair_off_method"] == "BEST_EFFORTS_ADMIN_ONLY"
        assert best_efforts_paired["pair_off_fee_cents"] == 25000
        assert (
            mandatory_paired["pair_off_fee_cents"]
            - best_efforts_paired["pair_off_fee_cents"]
            == 372400
        )

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["fee_receivable_cents"] == 422400
        assert seller["open_mandatory_exposure_cents"] == 0


class TestScorecardDefectRateDualVariant:
    """The count-weighted governing rate versus the balance-weighted report."""

    @staticmethod
    def _two_purchased_loans_and_an_open_scorecard() -> dict:
        """One defective 40,000,000 loan and one clean 90,000,000 loan."""
        fixtures.setup_clock("2026-08-01T00:00:00Z")
        conforming = fixtures.setup_product()
        fixtures.setup_pricing_adjustment(conforming["id"])
        jumbo = fixtures.setup_product(
            product_code="JUMBO30F",
            base_price_pct=100.500,
            min_fico=720,
            max_ltv_pct=80.0,
            max_loan_amount_cents=250000000,
            allowed_commitment_types=["MANDATORY"],
            allowed_occupancies=["PRIMARY"],
            srp_pct=0.750,
        )
        approved = fixtures.setup_approved_seller()
        seller_id = approved["seller_id"]

        conforming_line = fixtures.setup_commitment(
            seller_id, conforming["id"], notional_amount_cents=40000000
        )
        jumbo_line = fixtures.setup_commitment(
            seller_id,
            jumbo["id"],
            notional_amount_cents=90000000,
            reference_fico=760,
            reference_ltv_pct=78.0,
        )

        defective_loan = fixtures.deliver_loan(
            conforming_line["id"],
            seller_id,
            seller_loan_number="HP-1001",
            note_amount_cents=40000000,
            servicing_election="RELEASED",
            escrow_balance_cents=320000,
            closing_date="2026-07-20",
        )
        clean_loan = fixtures.deliver_loan(
            jumbo_line["id"],
            seller_id,
            seller_loan_number="HP-1002",
            note_amount_cents=90000000,
            note_rate_pct=6.000,
            fico=760,
            ltv_pct=78.0,
            escrow_balance_cents=0,
        )

        fixtures.open_loan_review(defective_loan["id"])
        defect = fixtures.record_defect(
            defective_loan["id"], "CR-DTI-OVERSTATED", "CREDIT", "HIGH"
        )
        fixtures.waive_defect(defect["id"], -25)
        fixtures.clear_loan_for_purchase(defective_loan["id"])

        fixtures.open_loan_review(clean_loan["id"])
        fixtures.clear_loan_for_purchase(clean_loan["id"])

        fixtures.setup_clock("2026-08-05T00:00:00Z")
        for loan, reference in ((defective_loan, "WIRE-1001"), (clean_loan, "WIRE-1002")):
            advice = fixtures.issue_purchase_advice(loan["id"])
            fixtures.settle_purchase_advice(advice["id"], reference)

        scorecard = fixtures.open_scorecard(seller_id, "2026-08-01", "2026-08-31")
        fixtures.setup_clock("2026-09-01T00:00:00Z")
        return {
            "seller_id": seller_id,
            "scorecard": scorecard,
            "defective_loan": defective_loan,
            "clean_loan": clean_loan,
        }

    def test_count_weighted_rate_governs_the_grade_and_standing_action(self):
        """One defective loan out of two is 5000 bps, grading C without a breach.

        The count-weighted rate ignores the fact that the defective loan is the
        smaller of the two, so the scorecard grades C, records no breach because
        5000 is not strictly above 5000, and hands the seller a watch action.

        PRD: "This is a count-weighted rate: every loan carries equal weight
        regardless of size."

        Design: Difficulty/dual_variant_calc/scorecard_defect_rate_loan_count_vs_upb_weighted
        """
        staged = self._two_purchased_loans_and_an_open_scorecard()

        closed = validate_success(
            api_client.close_scorecard(staged["scorecard"]["id"], ANALYST, {}), 200
        )

        assert_seller_scorecard(closed)
        assert closed["purchased_loan_count"] == 2
        assert closed["purchased_upb_cents"] == 130000000
        assert closed["defective_loan_count"] == 1
        assert closed["defective_upb_cents"] == 40000000
        assert closed["defect_rate_bps"] == 5000
        assert closed["grade"] == "C"
        assert closed["breach"] is False
        assert closed["standing_action_applied"] == "WATCH"
        assert closed["status"] == "CLOSED"

        seller = fixtures.read_seller(staged["seller_id"])
        assert seller["current_defect_rate_bps"] == 5000
        assert seller["current_scorecard_grade"] == "C"
        assert seller["delivery_standing"] == "WATCH"
        assert seller["approval_status"] == "APPROVED"

    def test_balance_weighted_rate_is_published_but_never_drives_the_outcome(self):
        """The reporting rate is 3077 bps and changes nothing about the grade.

        Weighting by unpaid balance divides 40,000,000 defective by 130,000,000
        scored, which rounds to 3077 basis points. That figure would grade B, yet
        the scorecard still grades C from the 5000-bps governing rate.

        PRD: "It is never used to grade the seller, never used to set the breach
        flag, and never used to drive a suspension, even when it is dramatically
        higher than the governing rate because the defective loans happened to be
        the large ones."

        Design: Difficulty/dual_variant_calc/scorecard_defect_rate_loan_count_vs_upb_weighted
        """
        staged = self._two_purchased_loans_and_an_open_scorecard()

        closed = validate_success(
            api_client.close_scorecard(staged["scorecard"]["id"], ANALYST, {}), 200
        )

        assert closed["upb_weighted_defect_rate_bps"] == 3077
        assert closed["defect_rate_bps"] == 5000
        assert closed["upb_weighted_defect_rate_bps"] < closed["defect_rate_bps"]
        assert closed["grade"] == "C"
        assert closed["breach"] is False
        assert closed["standing_action_applied"] == "WATCH"
