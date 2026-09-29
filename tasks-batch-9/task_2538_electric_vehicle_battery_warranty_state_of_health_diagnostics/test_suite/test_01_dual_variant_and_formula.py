"""Variant divergence and per-line rounding in the retention and money paths.

Every test here drives the same canonical five-row telemetry window into a
diagnostic and then into a settlement, and pins the figure the PRD uniquely
derives — the trimmed mean, the two nominal bases, the four separately rounded
cost lines and the administration tier keyed on the OEM share.
"""

import pytest

from test_helpers import (
    add_assessment,
    add_claim,
    add_sibling_vehicle,
    adjudicate,
    assert_settlement_waterfall,
    assert_soh_assessment,
    ingest_snapshot,
    read_program,
    setup_base_world,
)

# A vehicle deep enough into the goodwill band to prorate: 102 elapsed months
# against a 96-month coverage term, and 108,000 miles against 100,000.
GOODWILL_IN_SERVICE_DATE = "2018-01-15"
GOODWILL_SNAPSHOTS = [
    ("2026-07-20T00:00:00Z", 107200, 55.000),
    ("2026-07-22T00:00:00Z", 107400, 56.000),
    ("2026-07-24T00:00:00Z", 107600, 56.000),
    ("2026-07-26T00:00:00Z", 107800, 56.000),
    ("2026-07-28T00:00:00Z", 108000, 57.000),
]


class TestVariantRetentionBasis:
    """The two diagnostic variants answer the same question differently."""

    def test_telematics_window_and_bench_derated_basis_diverge_by_ten_points(self, api):
        """One measured capacity, two variants, two retention figures.

        PRD 3.3: "For `TELEMATICS_FLEET`, the denominator `nominal_basis_kwh` is
        the pack's full beginning-of-life `nominal_capacity_kwh`; faulted modules
        are *not* excluded from it." And: "For `BENCH_CAPACITY_TEST`, the
        numerator is simply `bench_measured_capacity_kwh`, and the denominator is
        derated pro rata for faulted modules."

        Design: Difficulty/dual_variant_calc/soh_retention_telematics_window_vs_bench_derated_basis
        """
        fleet_world = setup_base_world(api, snapshot_overrides={"coolant_temp_c": 20.0})
        bench_world = add_sibling_vehicle(
            api,
            fleet_world,
            vin="5YJ3E1EA7KF000002",
            serial_number="PK-C002",
        )
        ingest_snapshot(
            api,
            bench_world["vehicle_id"],
            "2026-07-28T00:00:00Z",
            71800,
            56.000,
            coolant_temp_c=20.0,
        )

        fleet = add_assessment(api, fleet_world, module_fault_positions=[3, 7])
        bench = add_assessment(
            api,
            bench_world,
            variant="BENCH_CAPACITY_TEST",
            bench_measured_capacity_kwh=56.000,
            module_fault_positions=[3, 7],
        )
        assert_soh_assessment(fleet)
        assert_soh_assessment(bench)

        # The trimmed mean drops 55.000 and 57.000 and averages the middle three.
        assert fleet["diagnostic_validity"] == "VALID"
        assert fleet["window_snapshot_count"] == 5
        assert fleet["estimated_capacity_kwh"] == pytest.approx(56.000, abs=0.001)
        assert fleet["nominal_basis_kwh"] == pytest.approx(80.000, abs=0.001)
        assert fleet["retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert fleet["assessed_odometer_miles"] == 71800
        assert fleet["elapsed_months"] == 76
        assert fleet["coverage_position"] == "IN_COVERAGE"
        assert fleet["applicable_min_retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert fleet["qualifies_for_claim"] is True

        # Two of sixteen modules faulted shrink the bench denominator to 70.000.
        assert bench["diagnostic_validity"] == "VALID"
        assert bench["estimated_capacity_kwh"] == pytest.approx(56.000, abs=0.001)
        assert bench["nominal_basis_kwh"] == pytest.approx(70.000, abs=0.001)
        assert bench["retention_pct"] == pytest.approx(80.00, abs=0.01)
        assert bench["assessed_odometer_miles"] == 71800
        assert bench["elapsed_months"] == 76
        assert bench["coverage_position"] == "IN_COVERAGE"
        assert bench["applicable_min_retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert bench["qualifies_for_claim"] is False

        assert bench["retention_pct"] - fleet["retention_pct"] == pytest.approx(
            10.00, abs=0.01
        )

    def test_bench_denominator_tracks_the_faulted_count_the_fleet_basis_ignores(self, api):
        """Only the bench variant shrinks its denominator as modules fault.

        PRD 3.3: "The consequence is that for one and the same measured capacity
        the two variants return different retention figures whenever any module is
        faulted, because only the bench variant shrinks the denominator."

        Design: Difficulty/dual_variant_calc/soh_retention_telematics_window_vs_bench_derated_basis
        """
        world = setup_base_world(api, snapshot_overrides={"coolant_temp_c": 20.0})

        clean = add_assessment(
            api, world, variant="BENCH_CAPACITY_TEST", bench_measured_capacity_kwh=56.000
        )
        assert clean["nominal_basis_kwh"] == pytest.approx(80.000, abs=0.001)
        assert clean["retention_pct"] == pytest.approx(70.00, abs=0.01)
        assert clean["qualifies_for_claim"] is True

        derated = add_assessment(
            api,
            world,
            variant="BENCH_CAPACITY_TEST",
            bench_measured_capacity_kwh=56.000,
            module_fault_positions=[3, 7],
        )
        assert derated["nominal_basis_kwh"] == pytest.approx(70.000, abs=0.001)
        assert derated["retention_pct"] == pytest.approx(80.00, abs=0.01)
        assert derated["qualifies_for_claim"] is False


class TestSettlementVariantCostShare:
    """Identical remedy costs settle differently under the two coverage variants."""

    def test_full_coverage_and_goodwill_prorated_split_the_same_cost_differently(self, api):
        """363,092 cents settles as 370,592 in coverage and 169,455 in goodwill.

        PRD 3.5: "Under `FULL_COVERAGE` the owner pays nothing, the OEM share
        equals the whole remedy cost, and the administration tier is evaluated
        against that full figure. Under `GOODWILL_PRORATED` the owner share is
        positive and the OEM share shrinks — which can drop it into a *lower*
        administration tier than the same remedy cost would have hit under full
        coverage. Identical remedy costs consequently yield different
        `oem_total_cents` figures under the two settlement variants."

        Design: Difficulty/dual_variant_calc/settlement_full_coverage_vs_goodwill_prorated_cost_share
        """
        covered = setup_base_world(api, snapshot_overrides={"coolant_temp_c": 20.0})
        goodwill = add_sibling_vehicle(
            api,
            covered,
            vin="5YJ3E1EA7KF000003",
            serial_number="PK-C003",
            vehicle_overrides={"in_service_date": GOODWILL_IN_SERVICE_DATE},
            snapshots=GOODWILL_SNAPSHOTS,
            snapshot_overrides={"coolant_temp_c": 20.0},
        )

        add_assessment(api, covered, module_fault_positions=[3, 7])
        add_claim(api, covered)
        covered_claim = adjudicate(api, covered, "MODULE_REPLACEMENT")

        goodwill_assessment = add_assessment(api, goodwill, module_fault_positions=[3, 7])
        add_claim(api, goodwill)
        goodwill_claim = adjudicate(api, goodwill, "MODULE_REPLACEMENT")

        assert goodwill_assessment["elapsed_months"] == 102
        assert goodwill_assessment["assessed_odometer_miles"] == 108000
        assert goodwill_assessment["coverage_position"] == "GOODWILL_BAND"

        assert_settlement_waterfall(covered_claim)
        assert_settlement_waterfall(goodwill_claim)

        # The remedy cost is identical; only the split differs.
        assert covered_claim["remedy_cost_cents"] == 363092
        assert goodwill_claim["remedy_cost_cents"] == 363092

        assert covered_claim["settlement_variant"] == "FULL_COVERAGE"
        assert covered_claim["proration_factor"] == pytest.approx(0.0000, abs=0.0001)
        assert covered_claim["owner_share_cents"] == 0
        assert covered_claim["oem_share_cents"] == 363092
        assert covered_claim["admin_fee_cents"] == 7500
        assert covered_claim["oem_total_cents"] == 370592

        # Six months and 8,000 miles of overrun: max(6/12, 8000/15000) = 0.5333.
        assert goodwill_claim["settlement_variant"] == "GOODWILL_PRORATED"
        assert goodwill_claim["proration_factor"] == pytest.approx(0.5333, abs=0.0001)
        assert goodwill_claim["owner_share_cents"] == 193637
        assert goodwill_claim["oem_share_cents"] == 169455
        assert goodwill_claim["admin_fee_cents"] == 0
        assert goodwill_claim["oem_total_cents"] == 169455

        program = read_program(api, covered["program_id"])
        assert program["accrued_liability_cents"] == 540047


# A centre able to take either hardware remedy, at the reference labour rate that
# makes each cost line land on a fraction of a cent.
HARDWARE_CENTER = {
    "name": "West HV Center",
    "hv_certification_level": "L3",
    "has_pack_lift": True,
    "labor_rate_cents_per_hour": 18333,
}


class TestRemedyCostLineRounding:
    """Each cost line is rounded on its own before the four are added."""

    def test_three_module_remedy_rounds_every_line_before_summation(self, api):
        """435,000 + 59,582 + 2,265 + 12,000 is 508,847, not 508,848.

        PRD 3.5: "The remedy cost is four line items, each rounded to whole cents
        on its own before the four are added." And: "`remedy_cost_cents` is the sum
        of those four rounded lines. Summing the raw products and rounding once at
        the end is not equivalent and is not permitted."

        Design: Difficulty/combinatorial_formula/remedy_cost_per_line_rounding_before_summation
        """
        world = setup_base_world(
            api,
            center_overrides=HARDWARE_CENTER,
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        add_assessment(api, world, module_fault_positions=[3, 7, 11])
        claim = add_claim(api, world)

        assert claim["recommended_remedy"] == "MODULE_REPLACEMENT"
        assert claim["recommendation_basis"] == "MODULE_FAULT"

        decided = adjudicate(api, world, "MODULE_REPLACEMENT")
        assert_settlement_waterfall(decided)

        # Parts 3 x 145,000 exact; labour 3.25 h x 18,333 = 59,582.25 -> 59,582;
        # hazmat 483.296 kg x 3/16 = 90.618 kg at 2,500 per 100 kg = 2,265.45 ->
        # 2,265; diagnostic 12,000 exact.
        assert decided["remedy_cost_cents"] == 508847
        assert decided["remedy_cost_cents"] != 508848

        assert decided["settlement_variant"] == "FULL_COVERAGE"
        assert decided["owner_share_cents"] == 0
        assert decided["oem_share_cents"] == 508847
        assert decided["admin_fee_cents"] == 15000
        assert decided["oem_total_cents"] == 523847

        program = read_program(api, world["program_id"])
        assert program["accrued_liability_cents"] == 523847

    def test_two_module_remedy_also_rounds_each_line_rather_than_the_total(self, api):
        """290,000 + 59,582 + 1,510 + 12,000 is 363,092, not 363,093.

        PRD 3.5: "`remedy_cost_cents` is the sum of those four rounded lines.
        Summing the raw products and rounding once at the end is not equivalent
        and is not permitted."

        Design: Difficulty/combinatorial_formula/remedy_cost_per_line_rounding_before_summation
        """
        world = setup_base_world(
            api,
            center_overrides=HARDWARE_CENTER,
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        add_assessment(api, world, module_fault_positions=[3, 7])
        add_claim(api, world)
        decided = adjudicate(api, world, "MODULE_REPLACEMENT")
        assert_settlement_waterfall(decided)

        # The raw products sum to 363,092.55, which would round up to 363,093.
        assert decided["remedy_cost_cents"] == 363092
        assert decided["remedy_cost_cents"] != 363093


class TestAdminFeeTierKey:
    """The administration fee is tiered on the OEM share, never on the remedy cost."""

    def test_prorated_share_drops_a_half_million_cent_remedy_into_the_middle_tier(self, api):
        """A 508,847-cent remedy attracts 7,500 cents, not 15,000, once prorated.

        PRD 3.5: "Sixth, `admin_fee_cents` is a tiered administration charge keyed
        on `oem_share_cents`, with each tier's lower bound inclusive: an OEM share
        below 200,000 cents attracts no administration fee at all, a share from
        200,000 up to but not including 500,000 cents attracts 7,500 cents, and a
        share of 500,000 cents or more attracts 15,000 cents."

        Design: Difficulty/combinatorial_formula/settlement_admin_fee_tier_keyed_on_oem_share_not_remedy_cost
        """
        world = setup_base_world(
            api,
            center_overrides=HARDWARE_CENTER,
            vehicle_overrides={"in_service_date": GOODWILL_IN_SERVICE_DATE},
            snapshots=GOODWILL_SNAPSHOTS,
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        assessment = add_assessment(api, world, module_fault_positions=[3, 7, 11])
        assert assessment["elapsed_months"] == 102
        assert assessment["assessed_odometer_miles"] == 108000
        assert assessment["coverage_position"] == "GOODWILL_BAND"

        add_claim(api, world)
        decided = adjudicate(api, world, "MODULE_REPLACEMENT")
        assert_settlement_waterfall(decided)

        assert decided["settlement_variant"] == "GOODWILL_PRORATED"
        assert decided["remedy_cost_cents"] == 508847
        assert decided["proration_factor"] == pytest.approx(0.5333, abs=0.0001)
        assert decided["owner_share_cents"] == 271368
        assert decided["oem_share_cents"] == 237479

        # The remedy cost clears 500,000 but the OEM share does not, so the middle
        # tier applies.
        assert decided["remedy_cost_cents"] >= 500000
        assert decided["oem_share_cents"] < 500000
        assert decided["admin_fee_cents"] == 7500
        assert decided["oem_total_cents"] == 244979

        assert (
            decided["owner_share_cents"] + decided["oem_share_cents"]
            == decided["remedy_cost_cents"]
        )

        program = read_program(api, world["program_id"])
        assert program["accrued_liability_cents"] == 244979
