"""Variant-selected arithmetic: emission deterioration and supplier defect rates.

Both families of calculation choose between two structurally different
formulas from stored data, so the same measurements land on different numbers
depending on which variant the contract selects.
"""

import pytest

from test_helpers import (
    build_certification_family,
    build_engine_platform,
    complete_durability_run,
    inspect_component_lot,
    read_durability_run,
    read_family,
    read_lot,
    read_supplier_scorecard,
    receive_component_lot,
    schedule_durability_run,
    build_supplier,
)

FULL_RUN_HOURS = 500
HALF_RUN_HOURS = 250
INITIAL_EMISSION = 5.00
FINAL_EMISSION = 6.40


def _family_with_scheduled_run(family_code, emission_standard, platform_code):
    """A family and its platform carrying exactly one scheduled durability run."""
    family = build_certification_family(
        family_code=family_code, emission_standard=emission_standard
    )
    platform = build_engine_platform(family["id"], platform_code=platform_code)
    run = schedule_durability_run(
        family["id"],
        platform["id"],
        initial_emission_g_per_kwh=INITIAL_EMISSION,
        target_hours=FULL_RUN_HOURS,
    )
    return family, platform, run


class TestDeteriorationVariantSelection:
    """The emission standard alone decides how the factor is applied."""

    def test_epa_phase3_run_applies_the_deterioration_factor_multiplicatively(
        self, canonical_clock
    ):
        """PRD §3.2: "A successful schedule creates the run in `status` `SCHEDULED` with its `df_method` projected from the family's `emission_standard` — `MULTIPLICATIVE` for `EPA_PHASE3` and `ADDITIVE` for `CARB_2024` — leaving `accumulated_hours`, `final_emission_g_per_kwh`, `computed_deterioration_factor` and `completed_at` empty and `extrapolated` false."
        PRD §3.2: "Under the `MULTIPLICATIVE` variant the raw factor is the final emission divided by the initial emission, a dimensionless ratio."
        PRD §3.2: "Under `MULTIPLICATIVE`, the certified emission is the family's `declared_baseline_emission_g_per_kwh` multiplied by the rounded deterioration factor."

        Design: Difficulty/dual_variant_calc/deterioration_factor_multiplicative_vs_additive_diverge
        """
        family, _, run = _family_with_scheduled_run(
            "2027-EPA-208SS", "EPA_PHASE3", "208SS"
        )
        assert run["df_method"] == "MULTIPLICATIVE"

        completed = complete_durability_run(
            run["id"],
            accumulated_hours=FULL_RUN_HOURS,
            final_emission_g_per_kwh=FINAL_EMISSION,
        )
        assert completed["status"] == "COMPLETED"
        assert completed["extrapolated"] is False
        assert completed["computed_deterioration_factor"] == pytest.approx(
            1.2800, abs=0.00005
        )

        stored = read_family(family["id"])
        assert stored["deterioration_factor"] == pytest.approx(1.2800, abs=0.00005)
        assert stored["certified_emission_g_per_kwh"] == pytest.approx(5.12, abs=0.005)
        assert stored["compliance_margin_pct"] == pytest.approx(36.00, abs=0.005)
        assert stored["status"] == "DURABILITY_COMPLETE"

    def test_carb_2024_run_applies_the_deterioration_factor_additively(
        self, canonical_clock
    ):
        """PRD §3.2: "Under the `ADDITIVE` variant the raw factor is the final emission minus the initial emission, an offset expressed in grams per kilowatt-hour."
        PRD §3.2: "Under `ADDITIVE`, the certified emission is the family's `declared_baseline_emission_g_per_kwh` plus the rounded deterioration factor."
        PRD §3.2: "The three results are written to the family as `deterioration_factor`, `certified_emission_g_per_kwh` and `compliance_margin_pct`, and the family advances to `DURABILITY_COMPLETE`."

        Design: Difficulty/dual_variant_calc/deterioration_factor_multiplicative_vs_additive_diverge
        """
        family, _, run = _family_with_scheduled_run(
            "2027-CARB-208SS", "CARB_2024", "208SS-C"
        )
        assert run["df_method"] == "ADDITIVE"

        completed = complete_durability_run(
            run["id"],
            accumulated_hours=FULL_RUN_HOURS,
            final_emission_g_per_kwh=FINAL_EMISSION,
        )
        assert completed["computed_deterioration_factor"] == pytest.approx(
            1.4000, abs=0.00005
        )

        stored = read_family(family["id"])
        assert stored["deterioration_factor"] == pytest.approx(1.4000, abs=0.00005)
        assert stored["certified_emission_g_per_kwh"] == pytest.approx(5.40, abs=0.005)
        assert stored["compliance_margin_pct"] == pytest.approx(32.50, abs=0.005)
        assert stored["status"] == "DURABILITY_COMPLETE"

    def test_identical_readings_certify_the_two_standards_at_different_emissions(
        self, canonical_clock
    ):
        """PRD §3.2: "Because the two variants apply the same scaling factor in structurally different places, the same measured readings produce a materially different certified emission depending on whether the family is an `EPA_PHASE3` family or a `CARB_2024` family; that divergence is intentional and must not be smoothed over."
        PRD §3.2: "The compliance margin is the family's `family_emission_limit_g_per_kwh` minus the rounded certified emission, divided by that same `family_emission_limit_g_per_kwh`, multiplied by 100, and rounded half up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/deterioration_factor_multiplicative_vs_additive_diverge
        """
        epa_family, _, epa_run = _family_with_scheduled_run(
            "2027-EPA-208SS", "EPA_PHASE3", "208SS"
        )
        carb_family, _, carb_run = _family_with_scheduled_run(
            "2027-CARB-208SS", "CARB_2024", "208SS-C"
        )

        for run_id in (epa_run["id"], carb_run["id"]):
            complete_durability_run(
                run_id,
                accumulated_hours=FULL_RUN_HOURS,
                final_emission_g_per_kwh=FINAL_EMISSION,
            )

        epa = read_family(epa_family["id"])
        carb = read_family(carb_family["id"])
        assert epa["certified_emission_g_per_kwh"] != carb["certified_emission_g_per_kwh"]
        assert epa["certified_emission_g_per_kwh"] == pytest.approx(5.12, abs=0.005)
        assert carb["certified_emission_g_per_kwh"] == pytest.approx(5.40, abs=0.005)
        assert epa["compliance_margin_pct"] == pytest.approx(36.00, abs=0.005)
        assert carb["compliance_margin_pct"] == pytest.approx(32.50, abs=0.005)


class TestExtrapolationScalesPerVariant:
    """A run stopped short of the durability period scales differently per variant."""

    def test_multiplicative_extrapolation_scales_the_ratio_around_one(
        self, canonical_clock
    ):
        """PRD §3.2: "The run's `extrapolated` flag is set true exactly when `accumulated_hours` is strictly less than the family's `durability_hours`, and false otherwise."
        PRD §3.2: "When the flag is true, the scaling factor is the family's `durability_hours` divided by the run's `accumulated_hours`; when it is false, the scaling factor is 1."
        PRD §3.2: "Under `MULTIPLICATIVE`, the deterioration factor is 1 plus the quantity (the raw factor minus 1) multiplied by the scaling factor."

        Design: Difficulty/dual_variant_calc/deterioration_extrapolation_scaling_diverges_per_variant
        """
        family, _, run = _family_with_scheduled_run(
            "2027-EPA-208XT", "EPA_PHASE3", "208XT-E"
        )
        completed = complete_durability_run(
            run["id"],
            accumulated_hours=HALF_RUN_HOURS,
            final_emission_g_per_kwh=FINAL_EMISSION,
        )
        assert completed["extrapolated"] is True
        assert completed["computed_deterioration_factor"] == pytest.approx(
            1.5600, abs=0.00005
        )

        stored = read_family(family["id"])
        assert stored["certified_emission_g_per_kwh"] == pytest.approx(6.24, abs=0.005)
        assert stored["compliance_margin_pct"] == pytest.approx(22.00, abs=0.005)
        assert stored["status"] == "DURABILITY_COMPLETE"

    def test_additive_extrapolation_scales_the_offset_around_zero(
        self, canonical_clock
    ):
        """PRD §3.2: "Under `ADDITIVE`, the deterioration factor is simply the raw factor multiplied by the scaling factor."
        PRD §3.2: "The result is then rounded half up to 4 decimal places and written to the run's `computed_deterioration_factor`."

        Design: Difficulty/dual_variant_calc/deterioration_extrapolation_scaling_diverges_per_variant
        """
        family, _, run = _family_with_scheduled_run(
            "2027-CARB-208XT", "CARB_2024", "208XT-C"
        )
        completed = complete_durability_run(
            run["id"],
            accumulated_hours=HALF_RUN_HOURS,
            final_emission_g_per_kwh=FINAL_EMISSION,
        )
        assert completed["extrapolated"] is True
        assert completed["computed_deterioration_factor"] == pytest.approx(
            2.8000, abs=0.00005
        )

        stored = read_family(family["id"])
        assert stored["certified_emission_g_per_kwh"] == pytest.approx(6.80, abs=0.005)
        assert stored["compliance_margin_pct"] == pytest.approx(15.00, abs=0.005)

    def test_the_same_shortfall_costs_the_additive_family_more_margin(
        self, canonical_clock
    ):
        """PRD §3.2: "**Step three — applying the scale, which differs between the variants because a ratio is anchored at one while an offset is anchored at zero.** Under `MULTIPLICATIVE`, the deterioration factor is 1 plus the quantity (the raw factor minus 1) multiplied by the scaling factor."
        PRD §3.2: "Under `ADDITIVE`, the deterioration factor is simply the raw factor multiplied by the scaling factor."

        Design: Difficulty/dual_variant_calc/deterioration_extrapolation_scaling_diverges_per_variant
        """
        epa_family, _, epa_run = _family_with_scheduled_run(
            "2027-EPA-208XT", "EPA_PHASE3", "208XT-E"
        )
        carb_family, _, carb_run = _family_with_scheduled_run(
            "2027-CARB-208XT", "CARB_2024", "208XT-C"
        )
        for run_id in (epa_run["id"], carb_run["id"]):
            complete_durability_run(
                run_id,
                accumulated_hours=HALF_RUN_HOURS,
                final_emission_g_per_kwh=FINAL_EMISSION,
            )

        epa = read_family(epa_family["id"])
        carb = read_family(carb_family["id"])
        assert epa["compliance_margin_pct"] == pytest.approx(22.00, abs=0.005)
        assert carb["compliance_margin_pct"] == pytest.approx(15.00, abs=0.005)
        assert epa["compliance_margin_pct"] - carb["compliance_margin_pct"] == (
            pytest.approx(7.00, abs=0.005)
        )
        assert read_durability_run(epa_run["id"])["extrapolated"] is True
        assert read_durability_run(carb_run["id"])["extrapolated"] is True


class TestSupplierDefectRateVariants:
    """The stored pooled rate and the scorecard average weight lots differently."""

    def test_pooled_defect_rate_over_unequal_samples_drives_probation(
        self, canonical_clock
    ):
        """PRD §3.4: "The pooled rate is the sum of `defects_found` across that population, divided by the sum of `sample_size` across the same population, multiplied by one million, rounded half up to a whole number, and stored as `rolling_defect_ppm`."
        PRD §3.4: "Otherwise: if the recomputed pooled rate is **greater than** 100,000 parts per million, the supplier becomes `SUSPENDED` and its `incoming_inspection_level` becomes `TIGHTENED`; else if the pooled rate is **greater than** 25,000 parts per million, the supplier becomes `PROBATION` and its level becomes `TIGHTENED`; else the supplier becomes `APPROVED` and its level is chosen from the accepted-lot streak — `SKIP_LOT` when `consecutive_accepted_lots` is at least 5, `REDUCED` when it is at least 3, and `NORMAL` otherwise."
        PRD §3.4: "A rejection sets `accepted_qty` to 0 and `remaining_qty` to 0, writes `defect_ppm` in exactly the same way, records `inspected_by_user_id` in exactly the same way, adds 1 to the supplier's `inspected_lot_count`, **resets** the supplier's `consecutive_accepted_lots` to 0, and recomputes `rolling_defect_ppm`."

        Design: Difficulty/dual_variant_calc/supplier_ppm_pooled_vs_per_lot_average_diverge
        """
        supplier = build_supplier(
            supplier_code="SUP-CARB",
            name="Kirin Carburetor Works",
            component_category="CARBURETOR",
        )
        big_lot = receive_component_lot(
            supplier["id"], lot_code="CB-001", lot_quantity=800
        )
        assert big_lot["sample_size"] == 40
        assert big_lot["acceptance_number"] == 4
        accepted = inspect_component_lot(big_lot["id"], defects_found=0)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["defect_ppm"] == 0

        small_lot = receive_component_lot(
            supplier["id"], lot_code="CB-002", lot_quantity=200
        )
        assert small_lot["sample_size"] == 10
        assert small_lot["acceptance_number"] == 1

        rejected = inspect_component_lot(small_lot["id"], defects_found=2)
        assert rejected["status"] == "REJECTED"
        assert rejected["defect_ppm"] == 200000

        scorecard = read_supplier_scorecard(supplier["id"])
        assert scorecard["rolling_defect_ppm"] == 40000
        assert scorecard["approval_status"] == "PROBATION"
        assert scorecard["incoming_inspection_level"] == "TIGHTENED"
        assert scorecard["consecutive_accepted_lots"] == 0
        assert scorecard["inspected_lot_count"] == 2

    def test_scorecard_average_weights_every_lot_equally_against_the_pooled_rate(
        self, canonical_clock
    ):
        """PRD §3.4: "That variant weights every lot equally instead of by sample size: for each inspected lot in `created_at` ascending order, its own rate is its `defects_found` divided by its `sample_size`, multiplied by one million, rounded half up to a whole number — the same quantity stored on the lot as `defect_ppm` — and the scorecard figure is the arithmetic mean of those already-rounded per-lot rates, itself rounded half up to a whole number and reported as `scorecard_average_ppm`."
        PRD §3.4: "Because a large clean lot and a small dirty lot count equally in the second variant and unequally in the first, the two figures can diverge sharply, and the scorecard exists precisely so that divergence is visible."

        Design: Difficulty/dual_variant_calc/supplier_ppm_pooled_vs_per_lot_average_diverge
        """
        supplier = build_supplier(
            supplier_code="SUP-CARB",
            name="Kirin Carburetor Works",
            component_category="CARBURETOR",
        )
        big_lot = receive_component_lot(
            supplier["id"], lot_code="CB-001", lot_quantity=800
        )
        inspect_component_lot(big_lot["id"], defects_found=0)

        small_lot = receive_component_lot(
            supplier["id"], lot_code="CB-002", lot_quantity=200
        )
        assert small_lot["sample_size"] == 10
        assert small_lot["acceptance_number"] == 1
        second = inspect_component_lot(small_lot["id"], defects_found=1)
        assert second["status"] == "ACCEPTED"
        assert second["defect_ppm"] == 100000

        assert read_lot(big_lot["id"])["defect_ppm"] == 0

        scorecard = read_supplier_scorecard(supplier["id"])
        # Pooled: 1 defect over 50 sampled pieces. Per lot: (0 + 100000) / 2.
        assert scorecard["rolling_defect_ppm"] == 20000
        assert scorecard["scorecard_average_ppm"] == 50000
        assert scorecard["scorecard_average_ppm"] != scorecard["rolling_defect_ppm"]
        assert scorecard["approval_status"] == "APPROVED"
        assert scorecard["criticality"] == "MAJOR"
