"""Two calculations that each have two variants, and the variants disagree."""
import pytest

from test_helpers import fixtures as fx


class TestRemediationVolumeVariants:
    def test_provisional_grid_variant_is_written_when_remediation_opens(self, api):
        """PRD §3.6: "When `contamination_class` is `ELEVATED` or `GROSS`, the project advances `ASSESSED → REMEDIATION_ACTIVE` and a five-part cascade fires: `contamination_disclosure_required` is latched true, `remediation_started` is latched true, `remediation_volume_cubic_yards` is recomputed under the `PROVISIONAL_GRID` variant with `remediation_volume_basis` set to `PROVISIONAL_GRID`, `remediation_cost_cents` is recomputed, and that cost change in turn re-runs the insurance waterfall over every one of the project's insurance notifications whose `status` is not `CLOSED`, rewriting each one's allocation and then re-deriving each one's `status`."
        PRD §3.7: "Otherwise the impacted footprint is the number of qualifying samples multiplied by 100.0 square feet, the grid cell each sample point is taken to represent; the depth is the greatest `depth_inches` among the qualifying samples converted to feet by dividing by 12; the footprint is multiplied by that depth to give cubic feet; that figure is divided by the 27 cubic feet in a cubic yard; and the quotient is rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/remediation_volume_provisional_grid_versus_final_surveyed
        """
        ctx = fx.project_remediation_active_gross()
        project = ctx["project"]

        assert project["remediation_volume_cubic_yards"] == pytest.approx(
            29.63, abs=0.01
        ), (
            "one impacted sample over a 100.0 square-foot cell at 96 inches of depth "
            "is 1 * 100.0 * (96/12) / 27 = 29.63 cubic yards, got "
            f"{project['remediation_volume_cubic_yards']}"
        )
        assert project["remediation_volume_basis"] == "PROVISIONAL_GRID", (
            "the basis must name the variant that produced the stored number, got "
            f"{project['remediation_volume_basis']}"
        )

    def test_reconciliation_rewrites_the_volume_under_the_final_surveyed_variant(
        self, api
    ):
        """PRD §3.5: "Reconciliation has one substantive effect beyond the state change: it recomputes the project's `remediation_volume_cubic_yards` under the **`FINAL_SURVEYED`** variant and sets `remediation_volume_basis` to `FINAL_SURVEYED`."
        PRD §3.5: "The tonnage is divided by a soil density of 1.35 tons per cubic yard, and the quotient is rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/remediation_volume_provisional_grid_versus_final_surveyed
        """
        ctx = fx.project_remediation_active_gross()

        invoiced = fx.billing_event(ctx["work_order"]["id"], "INVOICE")
        assert invoiced["billing_status"] == "INVOICED", (
            f"INVOICE moves BILLABLE to INVOICED, got {invoiced['billing_status']}"
        )
        assert invoiced["field_status"] == "FIELD_COMPLETE", (
            "the billing event must not disturb field progress, got "
            f"{invoiced['field_status']}"
        )

        reconciled = fx.billing_event(ctx["work_order"]["id"], "RECONCILE")
        assert reconciled["billing_status"] == "RECONCILED", (
            f"RECONCILE moves INVOICED to RECONCILED, got {reconciled['billing_status']}"
        )
        assert reconciled["field_status"] == "FIELD_COMPLETE", (
            "the field dimension stays where it was, got "
            f"{reconciled['field_status']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["remediation_volume_cubic_yards"] == pytest.approx(
            9.19, abs=0.01
        ), (
            "12.4 hauled tons divided by 1.35 tons per cubic yard is 9.185..., which "
            "rounds half up to 9.19, got "
            f"{project['remediation_volume_cubic_yards']}"
        )
        assert project["remediation_volume_basis"] == "FINAL_SURVEYED", (
            "the basis must now name the surveyed variant, got "
            f"{project['remediation_volume_basis']}"
        )

    def test_the_two_volume_variants_disagree_on_identical_project_data(self, api):
        """PRD §3.5: "Because it measures removed mass rather than impacted footprint, it will disagree with the provisional grid estimate that §3.7 describes even on identical project data; that disagreement is expected and is exactly why `remediation_volume_basis` exists."
        PRD §3.5: "It reads exactly one input — the project's `hauled_tons` as reported by the crew at field completion — and ignores every soil sample."

        Design: Difficulty/dual_variant_calc/remediation_volume_provisional_grid_versus_final_surveyed
        """
        ctx = fx.project_remediation_active_gross()
        provisional = ctx["project"]["remediation_volume_cubic_yards"]

        fx.billing_event(ctx["work_order"]["id"], "INVOICE")
        fx.billing_event(ctx["work_order"]["id"], "RECONCILE")
        surveyed = fx.read_project(ctx["project"]["id"])[
            "remediation_volume_cubic_yards"
        ]

        assert provisional == pytest.approx(29.63, abs=0.01), (
            f"grid estimate must be 29.63, got {provisional}"
        )
        assert surveyed == pytest.approx(9.19, abs=0.01), (
            f"surveyed figure must be 9.19, got {surveyed}"
        )
        assert (provisional - surveyed) == pytest.approx(20.44, abs=0.01), (
            "the two variants must diverge by 20.44 cubic yards on this project data, "
            f"got {provisional - surveyed}"
        )


class TestTrustFundVariantEligibility:
    #: Gross costs above the top cap tier, so the cap binds under both variants.
    CLAIMED_CENTS = 13000000

    def test_interim_variant_takes_the_deductible_out_of_the_capped_figure(self, api):
        """PRD §3.9: "Under `PRELIMINARY_ESTIMATE`, the cap is applied to the gross figure first and the deductible is then subtracted from the already-capped figure: take the capped figure less `deductible_cents`, floor that difference at zero, and subtract `admin_fee_cents`."
        PRD §3.9: "`admin_fee_cents` is the capped figure multiplied by the fund's administrative rate of three and a half percent, rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/trust_fund_preliminary_estimate_versus_final_settlement_eligibility
        """
        ctx = fx.project_cleared()
        claim = fx.create_claim(
            ctx["project"]["id"],
            variant="PRELIMINARY_ESTIMATE",
            claimed_costs_cents=self.CLAIMED_CENTS,
        )

        assert claim["cap_cents"] == 12500000, (
            "gross costs above 12,000,000 cents select the 12,500,000-cent tier, got "
            f"{claim['cap_cents']}"
        )
        assert claim["admin_fee_cents"] == 437500, (
            "3.5 percent of the 12,500,000-cent capped figure is 437,500 cents, got "
            f"{claim['admin_fee_cents']}"
        )
        assert claim["eligible_amount_cents"] == 12012500, (
            "12,500,000 capped less the 50,000-cent New Jersey deductible less the "
            f"437,500-cent fee is 12,012,500 cents, got {claim['eligible_amount_cents']}"
        )

    def test_close_out_variant_takes_the_deductible_out_of_the_gross_figure(self, api):
        """PRD §3.9: "Under `FINAL_SETTLEMENT`, the deductible is subtracted from the gross figure first and the cap is applied to the net: take the gross figure less `deductible_cents`, take the smaller of that difference and `cap_cents`, floor the result at zero, and subtract `admin_fee_cents`."
        PRD §3.9: "`deductible_cents` is taken from the state deductible schedule for the claim's snapshotted `state_code`: five hundred dollars for `NJ`, one thousand dollars for `NY`, two hundred fifty dollars for `CT`."

        Design: Difficulty/dual_variant_calc/trust_fund_preliminary_estimate_versus_final_settlement_eligibility
        """
        ctx = fx.project_cleared()
        claim = fx.create_claim(
            ctx["project"]["id"],
            variant="FINAL_SETTLEMENT",
            claimed_costs_cents=self.CLAIMED_CENTS,
        )

        assert claim["deductible_cents"] == 50000, (
            "a New Jersey site carries a 50,000-cent deductible, got "
            f"{claim['deductible_cents']}"
        )
        assert claim["cap_cents"] == 12500000, (
            "the cap tier is keyed on the gross figure, not the net, got "
            f"{claim['cap_cents']}"
        )
        assert claim["admin_fee_cents"] == 437500, (
            "the fee is keyed on the capped figure under both variants, got "
            f"{claim['admin_fee_cents']}"
        )
        assert claim["eligible_amount_cents"] == 12062500, (
            "12,950,000 net of the deductible capped at 12,500,000 less the "
            f"437,500-cent fee is 12,062,500 cents, got {claim['eligible_amount_cents']}"
        )

    def test_close_out_variant_exceeds_interim_variant_by_exactly_one_deductible(
        self, api
    ):
        """PRD §3.9: "For identical `claimed_costs_cents` above the cap, the close-out variant therefore yields an eligible amount exactly one deductible higher than the interim variant, because the interim variant makes the deductible come out of the reimbursable ceiling while the close-out variant makes it come out of the gross costs."
        PRD §3.9: "Every `PRELIMINARY_ESTIMATE` claim on the same project whose `status` is `DRAFT`, `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED` is transitioned to `WITHDRAWN`, and the code `SUPERSEDED_BY_FINAL_SETTLEMENT` is appended to that claim's `eligibility_findings`."

        Design: Difficulty/dual_variant_calc/trust_fund_preliminary_estimate_versus_final_settlement_eligibility
        """
        ctx = fx.project_cleared()
        interim = fx.create_claim(
            ctx["project"]["id"],
            variant="PRELIMINARY_ESTIMATE",
            claimed_costs_cents=self.CLAIMED_CENTS,
        )
        close_out = fx.create_claim(
            ctx["project"]["id"],
            variant="FINAL_SETTLEMENT",
            claimed_costs_cents=self.CLAIMED_CENTS,
        )

        delta = (
            close_out["eligible_amount_cents"] - interim["eligible_amount_cents"]
        )
        assert delta == 50000, (
            "the two variants must differ by exactly the 50,000-cent New Jersey "
            f"deductible, got {delta}"
        )

        withdrawn = fx.read_claim(interim["id"])
        assert withdrawn["status"] == "WITHDRAWN", (
            "filing the close-out application withdraws the interim one, got "
            f"{withdrawn['status']}"
        )
        assert "SUPERSEDED_BY_FINAL_SETTLEMENT" in withdrawn["eligibility_findings"], (
            "the withdrawal must be explained on the interim claim, got "
            f"{withdrawn['eligibility_findings']}"
        )
