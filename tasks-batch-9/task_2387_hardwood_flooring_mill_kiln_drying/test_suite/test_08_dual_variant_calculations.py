"""Two calculations that each exist in two variants which must diverge on the
same underlying data: the lot yield, and the warranty liability."""

import pytest

from test_helpers import (
    finalize_lot_payload,
    setup_finalized_grade_run,
    setup_line_only_submitted_claim,
    validate_success,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    SUPERVISOR,
    refetch_product_line,
    setup_approved_claim,
)


class TestLotYieldVariants:
    """The provisional yield is a milling figure and the final yield is a
    grading figure; closing a lot out must publish both."""

    def test_finalize_publishes_the_final_yield_beside_the_untouched_provisional(
        self, api
    ):
        """PRD 3.7: "A lot that milled 6000 board feet into 4680 net had a
        `provisional_yield_pct` of 78.00; credited at 3970.2625 board feet its
        `final_yield_pct` is 66.17 and it grades out, while a character-heavy run
        crediting only 2200.0000 board feet gives 36.67 and quarantines it."

        PRD 3.7: "The provisional figure is never overwritten — it remains the
        milling record — and only the final figure decides the branch."

        Design: Difficulty/dual_variant_calc/lot_yield_provisional_vs_final_diverge
        """
        ctx = setup_finalized_grade_run(api)

        response = api.finalize_flooring_lot(
            ctx["lot"]["id"], finalize_lot_payload(ctx["grade_run"]["id"]), SUPERVISOR
        )
        lot = validate_success(response, expected_status=200)

        assert lot["status"] == "GRADED"
        assert lot["provisional_yield_pct"] == pytest.approx(78.00, abs=0.01)
        assert lot["final_yield_pct"] == pytest.approx(66.17, abs=0.01)
        assert lot["final_yield_pct"] != lot["provisional_yield_pct"], (
            "the two variants must not collapse onto one number"
        )

    def test_yield_summary_exposes_both_variants_and_their_delta(self, api):
        """PRD 3.7: "A computed read exposes both variants side by side for a
        lot, returning its `flooring_lot_id`, the `input_dry_bf` drawn, the
        `net_flooring_bf` milled, the `residue_bf` and `waste_bf` from the mass
        balance, the `provisional_yield_pct` and `final_yield_pct` variants, a
        `yield_delta_pp` giving the final yield less the provisional yield in
        percentage points rounded half up to two decimal places, and the
        `yield_floor_pct` of 55.00 in force."

        Design: Difficulty/dual_variant_calc/lot_yield_provisional_vs_final_diverge
        """
        ctx = setup_finalized_grade_run(api)
        validate_success(
            api.finalize_flooring_lot(
                ctx["lot"]["id"], finalize_lot_payload(ctx["grade_run"]["id"]), SUPERVISOR
            ),
            expected_status=200,
        )

        summary = validate_success(
            api.get_yield_summary(ctx["lot"]["id"], SUPERVISOR), expected_status=200
        )

        assert summary["flooring_lot_id"] == ctx["lot"]["id"]
        assert summary["input_dry_bf"] == pytest.approx(6000, abs=0.01)
        assert summary["net_flooring_bf"] == pytest.approx(4680, abs=0.01)
        assert summary["provisional_yield_pct"] == pytest.approx(78.00, abs=0.01)
        assert summary["final_yield_pct"] == pytest.approx(66.17, abs=0.01)
        # The final yield less the provisional yield: 66.17 - 78.00.
        assert summary["yield_delta_pp"] == pytest.approx(-11.83, abs=0.01)
        assert summary["yield_floor_pct"] == pytest.approx(55.00, abs=0.01)


class TestWarrantyLiabilityVariants:
    """The intake estimate is informational; only the adjudicated charge moves
    the reserve."""

    def test_intake_estimate_and_adjudicated_charge_diverge_on_one_claim(self, api):
        """PRD 3.9: "On a line whose material value is 895 cents per square foot,
        a claim of 240 square feet gives a base of 328800, an administrative
        amount of 26304 and an estimate of 355104 cents."

        PRD 3.9: "A verified 210 square feet on the same 895-cent line gives a
        base of 287700, an administrative amount of 23016 and a gross of 310716;
        installed on 2026-03-15 and adjudicated on 2026-08-20 the claim has 5
        months of service and 2.5 percent depreciation, giving 302948; at a mill
        share of 50 percent the charge is 151474 cents."

        Design: Difficulty/dual_variant_calc/warranty_liability_estimated_vs_adjudicated_diverge
        """
        ctx = setup_line_only_submitted_claim(api)
        assert ctx["claim"]["estimated_liability_cents"] == 355104

        ctx = setup_approved_claim(api, ctx=ctx)
        claim = ctx["claim"]

        assert claim["adjudication_status"] == "APPROVED"
        assert claim["installer_share_pct"] == 50
        assert claim["mill_share_pct"] == 50
        assert claim["service_months"] == 5
        assert claim["depreciation_pct"] == pytest.approx(2.5, abs=0.01)
        assert claim["adjudicated_liability_cents"] == 151474
        assert claim["estimated_liability_cents"] == 355104, (
            "the intake estimate is a record of the claimant's own figures and is "
            "not replaced by the adjudicated charge"
        )

    def test_only_the_adjudicated_variant_moves_the_reserve(self, api):
        """PRD 3.9: "This figure is informational only — it never touches the
        reserve."

        PRD 3.9: "Otherwise the claim advances from `SUBMITTED` to `APPROVED`,
        the charge is debited from `warranty_balance_cents` and credited to
        `warranty_committed_cents`, and the line's posture is recomputed."

        Design: Difficulty/dual_variant_calc/warranty_liability_estimated_vs_adjudicated_diverge
        """
        ctx = setup_line_only_submitted_claim(api)

        line_before = refetch_product_line(api, ctx["product_line"]["id"])
        assert line_before["warranty_balance_cents"] == 600000
        assert line_before["warranty_committed_cents"] == 0

        ctx = setup_approved_claim(api, ctx=ctx)

        line_after = validate_success(
            api.get_product_line(ctx["product_line"]["id"], ADJUDICATOR),
            expected_status=200,
        )
        assert line_after["warranty_committed_cents"] == 151474
        assert line_after["warranty_balance_cents"] == 448526
        assert line_after["warranty_committed_cents"] != 355104, (
            "the informational estimate must never be the amount committed"
        )
