"""Derived figures: classification bands, grid geometry, fund arithmetic and precision."""
import pytest

from test_helpers import fixtures as fx, parse_instant


class TestContaminationBands:
    def test_a_result_between_the_two_tiers_lands_in_the_elevated_band(self, api):
        """PRD §3.6: "Otherwise `max_tph_mg_kg` is the highest `tph_mg_kg` in the set and `max_benzene_mg_kg` the highest `benzene_mg_kg`, and the class is decided by two tiers of strictly-greater-than comparisons: the class is `GROSS` when `max_tph_mg_kg` exceeds 5000.0 mg/kg or `max_benzene_mg_kg` exceeds 5.0 mg/kg; failing that it is `ELEVATED` when `max_tph_mg_kg` exceeds the 500.0 mg/kg action level or `max_benzene_mg_kg` exceeds the 0.5 mg/kg action level; and failing both it is `CLEAN`."
        PRD §3.6: "When `contamination_class` is `ELEVATED` or `GROSS`, the project advances `ASSESSED → REMEDIATION_ACTIVE` and a five-part cascade fires: `contamination_disclosure_required` is latched true, `remediation_started` is latched true, `remediation_volume_cubic_yards` is recomputed under the `PROVISIONAL_GRID` variant with `remediation_volume_basis` set to `PROVISIONAL_GRID`, `remediation_cost_cents` is recomputed, and that cost change in turn re-runs the insurance waterfall over every one of the project's insurance notifications whose `status` is not `CLOSED`, rewriting each one's allocation and then re-deriving each one's `status`."
        PRD §3.9: "The resulting codes are deduplicated and sorted lexicographically ascending — never by creation time or identifier — so the list is stable and directly comparable between reads. Closure requires it to be empty."

        Design: Corner/calculations/contamination_class_elevated_band_between_action_and_gross
        """
        ctx = fx.project_remediation_active_elevated()

        assert ctx["sample"]["status"] == "RESULTED", (
            f"the aliquot must carry a posted analysis, got {ctx['sample']['status']}"
        )

        project = ctx["project"]
        assert project["max_tph_mg_kg"] == pytest.approx(900.0, abs=0.01), (
            f"the single result is the round maximum, got {project['max_tph_mg_kg']}"
        )
        assert project["max_benzene_mg_kg"] == pytest.approx(0.2, abs=0.01), (
            f"the benzene maximum comes from the same row, got {project['max_benzene_mg_kg']}"
        )
        assert project["contamination_class"] == "ELEVATED", (
            "900.0 mg/kg is above the 500.0 action level but below the 5000.0 gross "
            f"level, and 0.2 mg/kg is below both benzene levels, got "
            f"{project['contamination_class']}"
        )
        assert project["status"] == "REMEDIATION_ACTIVE", (
            f"the elevated branch routes to remediation, got {project['status']}"
        )
        assert project["contamination_disclosure_required"] is True, (
            "the cascade latches the disclosure requirement"
        )
        assert project["remediation_started"] is True, (
            "the cascade latches the remediation flag"
        )
        assert project["remediation_volume_cubic_yards"] == pytest.approx(
            25.93, abs=0.01
        ), (
            "one impacted point over 100.0 square feet at 84 inches of depth is "
            "700 cubic feet, which is 25.93 cubic yards, got "
            f"{project['remediation_volume_cubic_yards']}"
        )
        assert project["remediation_volume_basis"] == "PROVISIONAL_GRID", (
            "nothing has been reconciled against a weigh ticket, got "
            f"{project['remediation_volume_basis']}"
        )
        assert project["remediation_cost_cents"] == 185000, (
            "with no approved change order the cost is the bare mobilization charge, "
            f"got {project['remediation_cost_cents']}"
        )
        assert project["nfa_blockers"] == [
            "CONTAMINATION_DISCLOSURE_NOT_ACKNOWLEDGED",
            "CONTAMINATION_NOT_CLEARED",
        ], (
            "exactly the two remediation obstacles remain, in ascending order, got "
            f"{project['nfa_blockers']}"
        )

    def test_the_grid_footprint_counts_only_the_points_over_the_action_level(self, api):
        """PRD §3.7: "The `PROVISIONAL_GRID` variant considers only the *impacted* samples: those on the project whose `sampling_round` equals the project's current round, whose `status` is `RESULTED`, and whose `tph_mg_kg` **strictly exceeds** the 500.0 mg/kg action level. If no sample qualifies, the volume is 0.00. Otherwise the impacted footprint is the number of qualifying samples multiplied by 100.0 square feet, the grid cell each sample point is taken to represent; the depth is the greatest `depth_inches` among the qualifying samples converted to feet by dividing by 12; the footprint is multiplied by that depth to give cubic feet; that figure is divided by the 27 cubic feet in a cubic yard; and the quotient is rounded half up to two decimal places."
        PRD §3.6: "The round is complete when the project has no sample in the current `sampling_round` whose `status` is `COLLECTED`, `IN_TRANSIT` or `AT_LAB`, and at least one whose `status` is `RESULTED`."

        Design: Corner/calculations/provisional_grid_volume_counts_only_samples_above_the_action_level
        """
        ctx = fx.project_at_sampling()
        deep_clean_point = fx.collect_sample_at_lab(
            ctx, sample_point="TANK_BOTTOM", depth_inches=96
        )
        shallow_impacted_point = fx.collect_sample_at_lab(
            ctx, sample_point="NORTH_SIDEWALL", depth_inches=60
        )

        mid = fx.report_result(
            deep_clean_point["id"], ctx["laboratory"]["id"], 480.0, 0.05
        )
        assert mid["status"] == "RESULTED", (
            f"the first analysis must post cleanly, got {mid['status']}"
        )
        assert fx.read_project(ctx["project"]["id"])["status"] == "SAMPLING", (
            "the round stays open while the second aliquot is unresulted"
        )

        fx.report_result(
            shallow_impacted_point["id"], ctx["laboratory"]["id"], 900.0, 0.2
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["contamination_class"] == "ELEVATED", (
            "classification uses the maximum across both rows, got "
            f"{project['contamination_class']}"
        )
        assert project["max_tph_mg_kg"] == pytest.approx(900.0, abs=0.01), (
            f"the higher of 480.0 and 900.0 is 900.0, got {project['max_tph_mg_kg']}"
        )
        assert project["remediation_volume_cubic_yards"] == pytest.approx(
            18.52, abs=0.01
        ), (
            "only the 900.0 mg/kg point qualifies, so the geometry is one 100.0 "
            "square-foot cell at 60 inches — 18.52 cubic yards, not the 59.26 that "
            "counting the 480.0 mg/kg point at 96 inches would give, got "
            f"{project['remediation_volume_cubic_yards']}"
        )
        assert project["remediation_volume_basis"] == "PROVISIONAL_GRID", (
            f"the grid estimate produced the figure, got {project['remediation_volume_basis']}"
        )
        assert project["status"] == "REMEDIATION_ACTIVE", (
            f"the elevated class routes to remediation, got {project['status']}"
        )


class TestTrustFundArithmetic:
    #: Gross costs low enough to stay inside the first reimbursement tier.
    CLAIMED_CENTS = 200000

    def test_a_connecticut_claim_uses_the_connecticut_deductible(self, api):
        """PRD §3.9: "`deductible_cents` is taken from the state deductible schedule for the claim's snapshotted `state_code`: five hundred dollars for `NJ`, one thousand dollars for `NY`, two hundred fifty dollars for `CT`."
        PRD §3.9: "`cap_cents` is the reimbursement ceiling selected by the gross figure across three tiers: forty thousand dollars when the gross figure is at most fifty thousand dollars; ninety thousand dollars when it is at most one hundred twenty thousand dollars; and one hundred twenty-five thousand dollars above that. In cents, the tier boundaries are 5,000,000 and 12,000,000, and the caps are 4,000,000, 9,000,000 and 12,500,000."
        PRD §3.9: "`admin_fee_cents` is the capped figure multiplied by the fund's administrative rate of three and a half percent, rounded half up to whole cents."
        PRD §3.1: "Registration also derives two read-only figures: `trust_fund_deductible_cents`, taken from the state deductible schedule for the property's `state_code`, and `open_project_count`, which starts at 0."

        Design: Corner/calculations/trust_fund_state_deductible_constant_selected_by_state_code
        """
        ctx = fx.project_cleared(
            property_overrides={
                "street_address": "22 Corner Way",
                "state_code": "CT",
                "county_code": "FAIRFIELD",
            }
        )

        assert ctx["property"]["trust_fund_deductible_cents"] == 25000, (
            "two hundred fifty dollars is the Connecticut deductible, got "
            f"{ctx['property']['trust_fund_deductible_cents']}"
        )

        claim = fx.create_claim(
            ctx["project"]["id"], claimed_costs_cents=self.CLAIMED_CENTS
        )
        assert claim["deductible_cents"] == 25000, (
            "the claim snapshots Connecticut's deductible rather than New Jersey's "
            f"50,000, got {claim['deductible_cents']}"
        )
        assert claim["cap_cents"] == 4000000, (
            "200,000 cents gross is inside the first tier, whose cap is 4,000,000, "
            f"got {claim['cap_cents']}"
        )
        assert claim["admin_fee_cents"] == 7000, (
            "three and a half percent of 200,000 cents is 7000, got "
            f"{claim['admin_fee_cents']}"
        )
        assert claim["eligible_amount_cents"] == 168000, (
            "200,000 less the 25,000 deductible less the 7000 fee is 168,000, got "
            f"{claim['eligible_amount_cents']}"
        )
        assert claim["unreimbursed_balance_cents"] == 168000, (
            "with nothing disbursed the balance is the whole eligible amount, got "
            f"{claim['unreimbursed_balance_cents']}"
        )
        assert claim["status"] == "DRAFT", (
            f"a freshly filed application sits in DRAFT, got {claim['status']}"
        )
        assert claim["reimbursed_amount_cents"] == 0, (
            f"no cash has moved yet, got {claim['reimbursed_amount_cents']}"
        )


class TestLaboratoryTimingPrecision:
    RECEIPT_INSTANT = "2026-08-06T14:00:00Z"
    REPORT_INSTANT = "2026-08-07T09:37:07Z"

    def test_turnaround_hours_round_half_up_rather_than_truncate(self, api):
        """PRD §3.6: "On success the sample transitions `AT_LAB → RESULTED`, `reported_at` is stamped from the logical clock, and two timing figures are derived: `turnaround_hours` is the interval from `received_at` to `reported_at` in hours rounded half up to two decimal places, and `turnaround_breach` is true only when that figure strictly exceeds the lab's `committed_turnaround_hours` — a turnaround landing exactly on the commitment is not a breach."
        PRD §3.6: "Second, the holding time is computed and checked: `holding_time_elapsed_hours` is the interval from `collected_at` to the current logical instant expressed in hours and rounded half up to two decimal places."
        PRD §3.6: "When `contamination_class` is `CLEAN`, the project advances `ASSESSED → CLEARED` and nothing else changes."

        Design: Corner/calculations/turnaround_hours_rounded_half_up_to_two_decimals
        """
        ctx = fx.project_at_sampling()
        sample = fx.create_sample(
            ctx["project"]["id"],
            ctx["work_order"]["id"],
            ctx["laboratory"]["id"],
            sample_point="CONFIRMATION_FLOOR",
            depth_inches=84,
        )
        fx.dispatch_sample(sample["id"])

        fx.set_clock(self.RECEIPT_INSTANT)
        received = fx.receive_sample(sample["id"], ctx["laboratory"]["id"])
        assert received["holding_time_elapsed_hours"] == pytest.approx(1.0, abs=0.01), (
            "the aliquot was collected an hour before it reached the bench, got "
            f"{received['holding_time_elapsed_hours']}"
        )

        fx.set_clock(self.REPORT_INSTANT)
        resulted = fx.report_result(sample["id"], ctx["laboratory"]["id"], 120.0, 0.05)

        assert parse_instant(resulted["reported_at"]) == parse_instant(

            self.REPORT_INSTANT

        ), (
            f"the report instant comes from the logical clock, got {resulted['reported_at']}"
        )
        assert resulted["turnaround_hours"] == pytest.approx(19.62, abs=0.01), (
            "70,627 seconds is 19.6186 hours, which rounds half up to 19.62 rather "
            f"than truncating to 19.61, got {resulted['turnaround_hours']}"
        )
        assert resulted["turnaround_breach"] is False, (
            "19.62 hours is well inside the 72-hour commitment, got "
            f"{resulted['turnaround_breach']}"
        )

        project = fx.read_project(ctx["project"]["id"])
        assert project["contamination_class"] == "CLEAN", (
            "120.0 mg/kg and 0.05 mg/kg are below both action levels, got "
            f"{project['contamination_class']}"
        )
        assert project["status"] == "CLEARED", (
            f"the clean branch clears the project outright, got {project['status']}"
        )
