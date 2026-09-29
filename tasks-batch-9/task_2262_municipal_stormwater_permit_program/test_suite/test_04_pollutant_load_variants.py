"""Annual pollutant load: the two variants, four-decimal samples and the allocation test."""

import pytest

from test_helpers import fixtures as fx
from test_helpers.assertions import assert_four_dp, assert_load_assessment, assert_two_dp


@pytest.fixture
def monitored_outfall():
    """A TMDL term at 50.00 lb/yr with OF-01 designed at 0.45 mg/L over 20000 kL."""
    program = fx.setup_active_program(
        outfall_codes=("OF-01",),
        tmdl=True,
        outfall_overrides={
            "receiving_water": "Mill Creek",
            "drainage_area_acres": 45.00,
            "priority_tier": "HIGH",
            "baseline_concentration_mg_per_l": 0.45,
            "design_runoff_kl": 20000,
            "sweeping_capacity_lane_miles_per_month": 40.00,
        },
        tmdl_wla_lb_per_year=50.00,
    )
    outfall = program["outfalls"]["OF-01"]
    fx.record_validated_sample(outfall["id"], "2026-03-10T14:00:00Z", 0.45, 40000)
    fx.record_validated_sample(outfall["id"], "2026-05-22T09:30:00Z", 0.62, 35000)
    fx.append_sweeping_run(outfall["id"], "2026-04-06", "2026-04-10", 20.00)
    return {"term_id": program["term_id"], "outfall": outfall}


class TestProvisionalAndFinalVariants:
    """Only the forward-looking variant values the samples the year still owes."""

    def test_01_provisional_values_the_two_owed_samples(self, monitored_outfall):
        """Two samples in hand of four expected: PROVISIONAL grosses 127.21 lb.

        PRD: "In the `PROVISIONAL` variant, each missing sample is valued at a
        projected unit load computed from the outfall's own design assumptions —
        `baseline_concentration_mg_per_l` multiplied by `design_runoff_kl`
        multiplied by the same 0.00220462 conversion factor, rounded to 4 decimal
        places — and the shortfall multiplied by that unit load is added to the
        taken total."

        Design: Difficulty/dual_variant_calc/pollutant_load_provisional_projects_owed_samples_final_does_not
        """
        assessment = fx.assess_load(monitored_outfall["outfall"]["id"], "PROVISIONAL", 2026)

        assert_load_assessment(
            assessment,
            variant="PROVISIONAL",
            gross_load_lb=127.21,
            sweeping_credit_lb=17.00,
            net_load_lb=110.21,
            tmdl_status="EXCEEDING",
            validated_sample_count=2,
            projected_sample_count=2,
        )

    def test_02_final_treats_the_shortfall_as_zero(self, monitored_outfall):
        """FINAL counts only the two validated samples and grosses 87.52 lb.

        PRD: "In the `FINAL` variant the projected shortfall is treated as zero,
        so only validated samples count."

        Design: Difficulty/dual_variant_calc/pollutant_load_provisional_projects_owed_samples_final_does_not
        """
        assessment = fx.assess_load(monitored_outfall["outfall"]["id"], "FINAL", 2026)

        assert_load_assessment(
            assessment,
            variant="FINAL",
            gross_load_lb=87.52,
            sweeping_credit_lb=17.00,
            net_load_lb=70.52,
            tmdl_status="EXCEEDING",
            validated_sample_count=2,
            projected_sample_count=0,
        )

    def test_03_the_whole_variant_difference_is_the_projected_term(self, monitored_outfall):
        """127.21 minus 87.52 is the two owed samples at 19.8416 lb each.

        PRD: "Four validated samples are expected per outfall per year; the
        projected shortfall is that expectation of four minus the number of
        validated samples in hand, never taken below zero."

        Design: Difficulty/dual_variant_calc/pollutant_load_provisional_projects_owed_samples_final_does_not
        """
        outfall_id = monitored_outfall["outfall"]["id"]
        provisional = fx.assess_load(outfall_id, "PROVISIONAL", 2026)
        final = fx.assess_load(outfall_id, "FINAL", 2026)

        difference = provisional["gross_load_lb"] - final["gross_load_lb"]
        assert difference == pytest.approx(39.69, abs=0.01), (
            "the variant difference must be two projected samples of 19.8416 lb, "
            f"got {difference}"
        )
        assert provisional["sweeping_credit_lb"] == pytest.approx(
            final["sweeping_credit_lb"], abs=0.01
        ), "the same 17.00 lb of earned credit sits below both variant caps"

    def test_04_only_the_final_variant_persists_onto_the_outfall(self, monitored_outfall):
        """A PROVISIONAL run leaves the outfall untouched; the FINAL run writes it.

        PRD: "A `PROVISIONAL` assessment persists nothing at all; its
        `tmdl_status` is returned for information only."

        Design: Difficulty/dual_variant_calc/pollutant_load_provisional_projects_owed_samples_final_does_not
        """
        outfall_id = monitored_outfall["outfall"]["id"]

        fx.assess_load(outfall_id, "PROVISIONAL", 2026)
        after_provisional = fx.read_outfall(outfall_id)
        assert after_provisional["tmdl_status"] == "NOT_ASSESSED", (
            "a provisional assessment must not write the outfall's tmdl_status"
        )
        assert after_provisional["last_assessed_year"] is None, (
            "a provisional assessment must not stamp last_assessed_year"
        )

        fx.assess_load(outfall_id, "FINAL", 2026)
        after_final = fx.read_outfall(outfall_id)

        assert after_final["tmdl_status"] == "EXCEEDING", (
            "70.52 lb exceeds the 50.00 lb allocation"
        )
        assert_two_dp(
            after_final["last_assessed_gross_load_lb"], 87.52, "last_assessed_gross_load_lb"
        )
        assert_two_dp(after_final["last_assessed_credit_lb"], 17.00, "last_assessed_credit_lb")
        assert_two_dp(
            after_final["last_assessed_net_load_lb"], 70.52, "last_assessed_net_load_lb"
        )
        assert after_final["last_assessed_year"] == 2026, "the assessed year is stamped"

    def test_05_the_final_exceedance_reaches_the_posture_census(self, monitored_outfall):
        """One exceeding outfall drives the term to AT_RISK.

        PRD: "A `FINAL` assessment writes `tmdl_status`,
        `last_assessed_gross_load_lb`, `last_assessed_credit_lb`,
        `last_assessed_net_load_lb` and `last_assessed_year` onto the outfall,
        then recomputes the term's `exceeding_outfall_count` and
        `compliance_posture` — which is how an exceedance reaches the posture
        census and, through it, the annual report gate."

        Design: Difficulty/dual_variant_calc/pollutant_load_provisional_projects_owed_samples_final_does_not
        """
        fx.assess_load(monitored_outfall["outfall"]["id"], "FINAL", 2026)

        term = fx.read_term(monitored_outfall["term_id"])
        assert term["exceeding_outfall_count"] == 1, "the single outfall is exceeding"
        assert term["compliance_posture"] == "AT_RISK", (
            "an exceeding outfall with no behind measure leaves the term AT_RISK"
        )


class TestSampleLoadPrecisionAndAllocationEquality:
    """Four decimals per sample, two for the totals, strict greater-than on the cap."""

    @pytest.fixture
    def two_outfalls(self):
        """A TMDL term at 50.00 lb/yr carrying OF-A and OF-B."""
        program = fx.setup_active_program(
            outfall_codes=("OF-A",), tmdl=True, tmdl_wla_lb_per_year=50.00,
            outfall_overrides={
                "receiving_water": "Mill Creek",
                "drainage_area_acres": 45.00,
                "priority_tier": "HIGH",
                "baseline_concentration_mg_per_l": 0.45,
                "design_runoff_kl": 20000,
                "sweeping_capacity_lane_miles_per_month": 40.00,
            },
        )
        outfall_b = fx.create_outfall(
            program["term_id"],
            "OF-B",
            receiving_water="Bell Slough",
            drainage_area_acres=9.00,
            priority_tier="LOW",
            baseline_concentration_mg_per_l=0.10,
            design_runoff_kl=5000,
            sweeping_capacity_lane_miles_per_month=10.00,
        )
        return {
            "term_id": program["term_id"],
            "outfall_a": program["outfalls"]["OF-A"],
            "outfall_b": outfall_b,
        }

    @pytest.mark.parametrize(
        "observed_at,concentration,volume,sample_load",
        [
            ("2026-03-10T09:00:00Z", 0.63, 36000, 50.0008),
            ("2026-04-02T09:00:00Z", 0.10, 5000, 1.1023),
            ("2026-05-18T09:00:00Z", 0.11, 21000, 5.0927),
        ],
    )
    def test_06_each_sample_load_is_carried_to_four_decimals(
        self, two_outfalls, observed_at, concentration, volume, sample_load
    ):
        """The per-sample pound figure keeps four decimal places.

        PRD: "`sample_load_lb` is the sample's `pollutant_concentration_mg_per_l`
        multiplied by its `runoff_volume_kl`, multiplied by the unit conversion
        factor 0.00220462 pounds per milligram-per-litre-kilolitre, rounded to 4
        decimal places."

        Design: Difficulty/boundary_precision_check/pollutant_load_holds_four_decimals_per_sample_and_treats_equality_as_attaining
        """
        sample = fx.record_validated_sample(
            two_outfalls["outfall_a"]["id"], observed_at, concentration, volume
        )

        assert_four_dp(sample["sample_load_lb"], sample_load, "sample_load_lb")

    def test_07_a_net_load_equal_to_the_allocation_is_attaining(self, two_outfalls):
        """50.0008 lb of sample rounds to a gross of 50.00, which attains.

        PRD: "Otherwise it is `EXCEEDING` when `net_load_lb` is strictly greater
        than the term's `tmdl_wla_lb_per_year`, and `ATTAINING` in every other
        case — a net load exactly equal to the allocation is `ATTAINING`."

        Design: Difficulty/boundary_precision_check/pollutant_load_holds_four_decimals_per_sample_and_treats_equality_as_attaining
        """
        outfall_id = two_outfalls["outfall_a"]["id"]
        fx.record_validated_sample(outfall_id, "2026-03-10T09:00:00Z", 0.63, 36000)

        assessment = fx.assess_load(outfall_id, "FINAL", 2026)

        assert_load_assessment(
            assessment,
            variant="FINAL",
            gross_load_lb=50.00,
            sweeping_credit_lb=0.00,
            net_load_lb=50.00,
            tmdl_status="ATTAINING",
            validated_sample_count=1,
            projected_sample_count=0,
        )

    def test_08_the_four_decimal_sample_sum_rounds_up_to_six_twenty(self, two_outfalls):
        """1.1023 plus 5.0927 is 6.1950, so the gross is 6.20 and not 6.19.

        PRD: "Their `sample_load_lb` values are summed to give the load actually
        taken."

        Design: Difficulty/boundary_precision_check/pollutant_load_holds_four_decimals_per_sample_and_treats_equality_as_attaining
        """
        outfall_id = two_outfalls["outfall_b"]["id"]
        fx.record_validated_sample(outfall_id, "2026-04-02T09:00:00Z", 0.10, 5000)
        fx.record_validated_sample(outfall_id, "2026-05-18T09:00:00Z", 0.11, 21000)

        assessment = fx.assess_load(outfall_id, "FINAL", 2026)

        assert_two_dp(assessment["gross_load_lb"], 6.20, "gross_load_lb")
        assert assessment["gross_load_lb"] != pytest.approx(6.19, abs=0.001), (
            "6.19 comes from carrying the products at full precision or from "
            "rounding each sample to 2 decimals before summing"
        )
        assert_two_dp(assessment["net_load_lb"], 6.20, "net_load_lb")
        assert assessment["tmdl_status"] == "ATTAINING", (
            "6.20 lb is far below the 50.00 lb allocation"
        )

    def test_09_two_attaining_assessments_leave_the_census_empty(self, two_outfalls):
        """Neither outfall enters the exceeding count.

        PRD: "`exceeding_outfall_count` is the number of outfalls of the term
        whose `status` is `ACTIVE` and whose `tmdl_status` is `EXCEEDING`."

        Design: Difficulty/boundary_precision_check/pollutant_load_holds_four_decimals_per_sample_and_treats_equality_as_attaining
        """
        fx.record_validated_sample(
            two_outfalls["outfall_a"]["id"], "2026-03-10T09:00:00Z", 0.63, 36000
        )
        fx.record_validated_sample(
            two_outfalls["outfall_b"]["id"], "2026-04-02T09:00:00Z", 0.10, 5000
        )
        fx.record_validated_sample(
            two_outfalls["outfall_b"]["id"], "2026-05-18T09:00:00Z", 0.11, 21000
        )

        fx.assess_load(two_outfalls["outfall_a"]["id"], "FINAL", 2026)
        fx.assess_load(two_outfalls["outfall_b"]["id"], "FINAL", 2026)

        term = fx.read_term(two_outfalls["term_id"])
        assert term["exceeding_outfall_count"] == 0, (
            "an attaining outfall never enters the exceeding census"
        )
        assert term["compliance_posture"] == "COMPLIANT", (
            "two attaining assessments leave the posture where it was"
        )
