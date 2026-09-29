"""Derived numeric values: the arithmetic the contract pins step by step.

Every check here fixes one calculation against the exact evaluation order the
specification prescribes: the hydraulic sizing chain from duty point to certified
suction requirement, the weighted pattern wear score, the casting piece ledger,
the ISO 1940 balance allowance, the handling-rate tier on a spare-parts
allocation, the three-level interchange ranking, the warranty coverage tier keyed
on whole months since shipment, the motor requirement's witness branch, and the
double rounding that sits inside the interpolated guarantee point.  Each test
asserts both the value the contract's own arithmetic produces and, where a
plausible shortcut would produce a different number, that the shortcut's number
is absent.
"""

import pytest

from test_helpers import (
    assert_kit_charge,
    assert_run_dimensions,
    assert_wear_index,
    constants as K,
    expected_allowable_unbalance,
    expected_coverage_factor,
    expected_handling_rate,
    expected_npsh_safety_factor,
    factories as F,
    fixtures as X,
    get_success_data,
    round_half_up,
    validate_success,
)
from test_helpers.test_users import (
    APPLICATION_ENGINEER,
    HYDRAULIC_APPROVER,
    PRODUCTION_PLANNER,
)

# The VTP-08 enquiry: 110.0 m3/h at 45.0 m, whose predicted efficiency of 72.93
# percent sits exactly on the contractual minimum and whose certified suction
# margin of 0.62 m clears the 0.60 m minimum, so the selection can be approved.
DUTY_FOR_VTP_08 = {
    "duty_flow_m3h": 110.0,
    "duty_head_m": 45.0,
    "npsha_available_m": 4.00,
    "min_efficiency_pct": 72.93,
    "witness_required": False,
}

# Five measured points at rated speed whose 250.0 and 280.0 members bracket the
# 265.0 guarantee flow with the guarantee flow exactly midway between them.
BRACKETING_CURVE_POINTS = [
    {"measured_flow_m3h": 150.0, "measured_head_m": 84.0, "measured_power_kw": 55.0},
    {"measured_flow_m3h": 200.0, "measured_head_m": 80.5, "measured_power_kw": 61.0},
    {
        "measured_flow_m3h": 250.0,
        "measured_head_m": 76.25,
        "measured_power_kw": 65.55,
        "measured_npsh3_m": 3.40,
        "is_npsh_point": True,
    },
    {"measured_flow_m3h": 280.0, "measured_head_m": 71.90, "measured_power_kw": 68.40},
    {"measured_flow_m3h": 330.0, "measured_head_m": 65.0, "measured_power_kw": 71.0},
]


# ─────────────────────────────────────────────────────────────────────────────
# Hydraulic sizing
# ─────────────────────────────────────────────────────────────────────────────
class TestSelectionDerivation:
    """One duty point pins trim, head, efficiency, power and certified suction."""

    def test_the_whole_sizing_chain_hangs_off_the_rounded_trimmed_diameter(
        self, api, engineer_headers
    ):
        """Sizing HSC-14 for 265.0 m3/h at 74.0 m derives every stored value.

        The curve constant is the shutoff head less the best-efficiency head
        divided by the square of the best-efficiency flow, so 20.0 over 90000,
        and it is never rounded.  The exact trim ratio is the square root of the
        duty head plus that constant times the square of the duty flow, over the
        shutoff head, and the trimmed diameter is that ratio times the full
        355.0 mm rounded half up to one decimal, 350.3 mm.  diameter_ratio is
        then recomputed from the already-rounded diameter rather than from the
        exact ratio, which is exactly why the predicted head comes back as
        73.97 m and not as the 74.00 m the duty point asked for.  Predicted
        efficiency, shaft power, the minimum motor rating and the five-step
        suction certification all follow from those same values, and creating the
        selection leaves it in DRAFT with no proposer recorded.

        Design: Corner/calculations/selection_computes_trim_head_efficiency_and_certified_npsh_from_the_duty_point
        """
        world = X.setup_master_data(api)
        duty = X.create_duty_application(api)

        response = api.create_selection(
            F.selection_payload(
                duty["id"], world["model"]["id"], world["config"]["id"], duty["version"]
            ),
            engineer_headers,
        )
        selection = validate_success(response, 201)

        assert selection["trimmed_impeller_diameter_mm"] == pytest.approx(
            K.SEL_1001_TRIMMED_DIAMETER_MM, abs=0.01
        )
        assert selection["predicted_head_m"] == pytest.approx(
            K.SEL_1001_PREDICTED_HEAD_M, abs=0.01
        )
        # The exact trim ratio would hand back the duty head untouched.
        assert selection["predicted_head_m"] != pytest.approx(74.00, abs=0.005)
        assert selection["predicted_efficiency_pct"] == pytest.approx(
            K.SEL_1001_PREDICTED_EFFICIENCY_PCT, abs=0.01
        )
        assert selection["predicted_shaft_power_kw"] == pytest.approx(65.96, abs=0.01)
        assert selection["min_motor_kw"] == pytest.approx(
            round_half_up(65.96 * K.MOTOR_MARGIN, 2), abs=0.01
        )
        assert selection["min_motor_kw"] == pytest.approx(72.56, abs=0.01)

        assert selection["npshr_catalog_m"] == pytest.approx(
            K.SEL_1001_NPSHR_CATALOG_M, abs=0.01
        )
        assert selection["npsh_provisional_margin_m"] == pytest.approx(
            K.SEL_1001_NPSH_PROVISIONAL_MARGIN_M, abs=0.01
        )
        assert selection["npsh_safety_factor"] == pytest.approx(
            expected_npsh_safety_factor(K.SEL_1001_NPSH_PROVISIONAL_MARGIN_M),
            abs=0.0001,
        )
        assert selection["npsh_safety_factor"] == pytest.approx(1.25, abs=0.0001)
        assert selection["npshr_certified_m"] == pytest.approx(
            K.SEL_1001_NPSHR_CERTIFIED_M, abs=0.01
        )
        assert selection["npsh_margin_m"] == pytest.approx(
            K.SEL_1001_NPSH_MARGIN_M, abs=0.01
        )

        assert selection["status"] == "DRAFT"
        assert selection["proposed_by_user_id"] is None
        assert selection["approved_by_user_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Pattern wear
# ─────────────────────────────────────────────────────────────────────────────
class TestPatternWearIndex:
    """One defect pour per lot, however many critical defects that lot carries."""

    def test_further_critical_defects_on_the_same_lot_do_not_advance_the_counter(
        self, api
    ):
        """A second critical defect on one lot leaves the wear score at three.

        The wear score is a weighted count: the index is pours since the last
        refurbishment plus twice the defect pours since that refurbishment, and
        the defect-pour counter advances only on the first critical defect
        reported against a given lot poured from that pattern.  One pour carrying
        two critical defects and one minor defect therefore scores one pour plus
        one defect pour, an index of 3, which stays under the pattern's
        withdrawal threshold of 5 so the tooling remains QUALIFIED and the model
        it produces remains ORDERABLE.  Counting each critical defect separately
        would score 5, reach the threshold and retire the pattern.

        Design: Corner/calculations/pattern_wear_index_counts_only_the_first_critical_defect_per_lot
        """
        world = X.setup_master_data(api, pattern={"wear_threshold": 5})
        lot = X.pour_casting_lot(api, world)
        X.report_defect(
            api,
            lot["id"],
            headers=world["foundry_headers"],
            defect_type="COLD_SHUT",
            severity="CRITICAL",
            affected_qty=1,
        )

        second_critical = api.report_casting_defect(
            lot["id"],
            F.casting_defect_payload(
                defect_type="MISRUN", severity="CRITICAL", affected_qty=1
            ),
            world["foundry_headers"],
        )
        validate_success(second_critical, 201)

        minor = api.report_casting_defect(
            lot["id"],
            F.casting_defect_payload(
                defect_type="POROSITY", severity="MINOR", affected_qty=1
            ),
            world["foundry_headers"],
        )
        validate_success(minor, 201)

        pattern = X.reread_pattern_asset(api, world["pattern"]["id"])
        assert pattern["pours_since_refurb"] == 1
        assert pattern["defect_pours_since_refurb"] == 1
        assert pattern["wear_index"] == 3
        assert_wear_index(pattern)
        assert pattern["status"] == "QUALIFIED"
        assert pattern["refurb_cycles"] == 0

        assert X.reread_pump_model(api, world["model"]["id"])["status"] == "ORDERABLE"


# ─────────────────────────────────────────────────────────────────────────────
# The casting piece ledger
# ─────────────────────────────────────────────────────────────────────────────
class TestCastingYieldLedger:
    """Only scrap and weld-repair dispositions move pieces out of acceptance."""

    def test_a_reported_then_use_as_is_defect_never_consumes_a_casting(
        self, api, inspector_headers
    ):
        """Six poured pieces stay six accepted across report and USE_AS_IS.

        The scrapped column sums the affected quantity of every defect on the lot
        that is dispositioned SCRAP, the rework column sums those dispositioned
        REPAIR, and the accepted count is the poured quantity less both sums;
        defects that are merely REPORTED, or dispositioned USE_AS_IS, contribute
        to neither.  Reporting a major defect on two of six pieces therefore
        leaves the accepted count at six, and dispositioning it USE_AS_IS leaves
        the piece ledger entirely unchanged, so no quarantine cascade can fire
        and the lot stays POURED.

        Design: Corner/calculations/casting_yield_ledger_ignores_reported_and_use_as_is_defects
        """
        world = X.setup_master_data(api)
        lot = X.pour_casting_lot(api, world, qty_poured=6)
        defect = X.report_defect(
            api,
            lot["id"],
            headers=world["foundry_headers"],
            defect_type="INCLUSION",
            severity="MAJOR",
            affected_qty=2,
        )

        while_reported = X.reread_casting_lot(api, lot["id"])
        assert while_reported["qty_accepted"] == 6
        assert while_reported["qty_scrapped"] == 0
        assert while_reported["qty_rework_pending"] == 0

        response = api.disposition_casting_defect(
            defect["id"], F.disposition_payload("USE_AS_IS"), inspector_headers
        )
        dispositioned = validate_success(response, 200)
        assert dispositioned["status"] == "DISPOSITIONED_USE_AS_IS"
        assert dispositioned["disposition"] == "USE_AS_IS"

        after = X.reread_casting_lot(api, lot["id"])
        assert after["qty_poured"] == 6
        assert after["qty_accepted"] == 6
        assert after["qty_scrapped"] == 0
        assert after["qty_rework_pending"] == 0
        assert after["status"] == "POURED"


# ─────────────────────────────────────────────────────────────────────────────
# ISO 1940 balance allowance
# ─────────────────────────────────────────────────────────────────────────────
class TestBalanceAllowance:
    """The balance quality number is read from the model's grade, not fixed."""

    def test_two_models_on_different_grades_get_different_allowances(
        self, api, planner_headers
    ):
        """A G2_5 rotor and a G6_3 rotor produce two different allowances.

        The balance quality number is 1.0 for G1_0, 2.5 for G2_5 and 6.3 for
        G6_3, and the allowable residual unbalance is that number multiplied by
        the ISO 1940 coefficient 9549, multiplied by the rotor mass, divided by
        the rated speed, rounded half up to two decimals.  VTP-08 is a G2_5 rotor
        of 40.0 kg at 1480 rpm and so is allowed 645.20 g mm, which a residual of
        exactly 645.20 passes because acceptance is inclusive, while HSC-14 is a
        G6_3 rotor of 68.0 kg at 2950 rpm and is allowed 1386.71 g mm.  A quality
        number hardwired to 6.3 would hand the light VTP-08 rotor the far larger
        allowance its grade does not entitle it to.

        Design: Corner/calculations/balance_allowance_reads_the_grade_g_table_not_a_fixed_coefficient
        """
        vtp = X.setup_planned_build_order(
            api,
            model=K.MODEL_VTP_08,
            config={"min_running_clearance_mm": 0.25},
            duty=DUTY_FOR_VTP_08,
            lot_overrides={"qty_poured": 3},
        )
        hsc = X.setup_planned_build_order(api)

        vtp_response = api.record_assembly(
            vtp["build_order"]["id"],
            F.assembly_payload(
                running_clearance_mm=0.40, residual_unbalance_g_mm=645.20
            ),
            planner_headers,
        )
        vtp_order = validate_success(vtp_response, 200)

        assert vtp_order["allowable_unbalance_g_mm"] == pytest.approx(645.20, abs=0.01)
        assert vtp_order["allowable_unbalance_g_mm"] == pytest.approx(
            expected_allowable_unbalance("G2_5", 40.0, 1480), abs=0.01
        )
        # A quality number hardwired to 6.3 would give a much larger allowance.
        assert vtp_order["allowable_unbalance_g_mm"] != pytest.approx(
            expected_allowable_unbalance("G6_3", 40.0, 1480), abs=0.01
        )
        assert vtp_order["status"] == "ASSEMBLED"

        vtp_selection = X.reread_selection(api, vtp["selection"]["id"])
        assert vtp_selection["trimmed_impeller_diameter_mm"] == pytest.approx(
            245.0, abs=0.01
        )
        assert vtp_selection["predicted_head_m"] == pytest.approx(45.02, abs=0.01)
        assert vtp_selection["predicted_efficiency_pct"] == pytest.approx(
            72.93, abs=0.01
        )
        assert vtp_selection["npsh_margin_m"] == pytest.approx(0.62, abs=0.01)

        hsc_response = api.record_assembly(
            hsc["build_order"]["id"], F.assembly_payload(), planner_headers
        )
        hsc_order = validate_success(hsc_response, 200)

        assert hsc_order["allowable_unbalance_g_mm"] == pytest.approx(
            K.BUILD_ALLOWABLE_UNBALANCE_G_MM, abs=0.01
        )
        assert hsc_order["allowable_unbalance_g_mm"] == pytest.approx(
            expected_allowable_unbalance("G6_3", 68.0, 2950), abs=0.01
        )
        assert hsc_order["allowable_unbalance_g_mm"] != pytest.approx(
            vtp_order["allowable_unbalance_g_mm"], abs=0.01
        )


# ─────────────────────────────────────────────────────────────────────────────
# Handling-rate tiers on a spare-parts allocation
# ─────────────────────────────────────────────────────────────────────────────
class TestKitHandlingRateTiers:
    """The handling tier is keyed on parts_extended, inclusive at 5000."""

    def test_the_dearer_kit_crosses_the_boundary_and_costs_less_in_total(
        self, api, planner_headers
    ):
        """5000.00 of parts sits in the 0.08 band and 5000.05 in the 0.05 band.

        The extended parts value is the requested quantity times the unit price
        times one plus a hundredth of the applied substitution penalty, rounded
        half up to two decimals.  The handling rate is then chosen from that
        value: 0.12 at 1000 or less, 0.08 above 1000 and at most 5000, 0.05 above
        5000 and at most 20000, and 0.03 beyond.  Five units at 1000.00 extend to
        exactly 5000.00, which the inclusive upper edge keeps in the 0.08 band
        for a 400.00 fee and a 5400.00 charge, while five units at 1000.01 extend
        to 5000.05, cross into the 0.05 band and total only 5250.05.  Keying the
        tier on the final charge, or making the boundary exclusive, would put both
        allocations in the same band.

        Design: Corner/calculations/kit_allocation_handling_rate_tier_flips_at_five_thousand_of_parts_value
        """
        ctx = X.setup_planned_build_order(api)
        kit_at_edge = X.setup_kit_with_stock(
            api, ctx["model"]["id"], qty=5, unit_price=1000.00
        )
        kit_above_edge = X.setup_kit_with_stock(
            api, ctx["model"]["id"], qty=5, unit_price=1000.01
        )

        edge_response = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit_at_edge["id"], ctx["build_order"]["id"], 5, kit_at_edge["version"]
            ),
            planner_headers,
        )
        at_edge = validate_success(edge_response, 201)

        above_response = api.create_kit_allocation(
            F.kit_allocation_payload(
                kit_above_edge["id"],
                ctx["build_order"]["id"],
                5,
                kit_above_edge["version"],
            ),
            planner_headers,
        )
        above_edge = validate_success(above_response, 201)

        assert at_edge["parts_extended"] == pytest.approx(5000.00, abs=0.005)
        assert at_edge["handling_rate"] == pytest.approx(0.08, abs=0.0001)
        assert at_edge["handling_rate"] == pytest.approx(
            expected_handling_rate(5000.00), abs=0.0001
        )
        assert at_edge["handling_fee"] == pytest.approx(400.00, abs=0.005)
        assert at_edge["total_charge"] == pytest.approx(5400.00, abs=0.005)
        assert_kit_charge(at_edge, 1000.00, 0.0)

        assert above_edge["parts_extended"] == pytest.approx(5000.05, abs=0.005)
        assert above_edge["handling_rate"] == pytest.approx(0.05, abs=0.0001)
        assert above_edge["handling_rate"] == pytest.approx(
            expected_handling_rate(5000.05), abs=0.0001
        )
        assert above_edge["handling_fee"] == pytest.approx(250.00, abs=0.005)
        assert above_edge["total_charge"] == pytest.approx(5250.05, abs=0.005)
        assert_kit_charge(above_edge, 1000.01, 0.0)

        assert above_edge["total_charge"] < at_edge["total_charge"]

        for allocation in (at_edge, above_edge):
            assert allocation["selected_by"] == "EXPLICIT"
            assert allocation["substitution_penalty_applied_pct"] == pytest.approx(
                0.0, abs=0.0001
            )

        for kit_id in (kit_at_edge["id"], kit_above_edge["id"]):
            kit = X.reread_repair_kit(api, kit_id)
            assert kit["qty_on_hand"] == 0
            assert kit["qty_reserved"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# The interchange selector
# ─────────────────────────────────────────────────────────────────────────────
class TestInterchangeSelector:
    """Exact generation preference outranks both penalty and list price."""

    def test_the_exact_generation_kit_wins_over_the_cheaper_substitute(
        self, api, planner_headers
    ):
        """A 980.00 exact-generation kit beats a 900.00 substitute.

        The candidate set is ranked on three ordered levels: kits whose preferred
        generation equals the model's generation rank ahead of those whose does
        not, then the lower substitution penalty, then the lower unit price.  For
        a generation-2 pump the kit preferring generation 2 therefore wins on the
        first level, before price is ever consulted, even though the substitute
        covering generations 1 to 3 lists cheaper.  The winning kit's preferred
        generation matches, so no substitution penalty is applied, the extended
        parts value is 980.00, the handling rate is the 0.12 band for 1000 or
        less, and the charge is 1097.60.  Ranking on price first would book the
        substitute's 958.50 of parts and a 1073.52 charge instead, and would move
        the wrong kit's stock.

        Design: Corner/calculations/interchange_selector_prefers_exact_generation_over_the_cheaper_substitute
        """
        ctx = X.setup_planned_build_order(api)
        exact_kit = X.setup_kit_with_stock(
            api,
            ctx["model"]["id"],
            qty=4,
            gen_min=2,
            gen_max=2,
            preferred_generation=2,
            substitution_penalty_pct=0.0,
            unit_price=980.00,
        )
        substitute_kit = X.setup_kit_with_stock(
            api,
            ctx["model"]["id"],
            qty=4,
            gen_min=1,
            gen_max=3,
            preferred_generation=3,
            substitution_penalty_pct=6.5,
            unit_price=900.00,
        )

        response = api.auto_allocate_kit(
            ctx["build_order"]["id"], F.auto_allocation_payload(1), planner_headers
        )
        allocation = validate_success(response, 201)

        assert allocation["repair_kit_id"] == exact_kit["id"]
        assert allocation["repair_kit_id"] != substitute_kit["id"]
        assert allocation["selected_by"] == "SELECTOR"
        assert allocation["substitution_penalty_applied_pct"] == pytest.approx(
            0.0, abs=0.0001
        )
        assert allocation["parts_extended"] == pytest.approx(980.00, abs=0.005)
        assert allocation["handling_rate"] == pytest.approx(0.12, abs=0.0001)
        assert allocation["handling_fee"] == pytest.approx(117.60, abs=0.005)
        assert allocation["total_charge"] == pytest.approx(1097.60, abs=0.005)
        assert_kit_charge(allocation, 980.00, 0.0)
        # The substitute's penalised parts value must not appear.
        assert allocation["parts_extended"] != pytest.approx(958.50, abs=0.005)
        assert allocation["total_charge"] != pytest.approx(1073.52, abs=0.005)

        chosen = X.reread_repair_kit(api, exact_kit["id"])
        assert chosen["qty_on_hand"] == 3
        assert chosen["qty_reserved"] == 1

        untouched = X.reread_repair_kit(api, substitute_kit["id"])
        assert untouched["qty_on_hand"] == 4
        assert untouched["qty_reserved"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Warranty coverage tiers
# ─────────────────────────────────────────────────────────────────────────────
class TestWarrantyCoverageTiers:
    """The coverage tier is stamped at submission on whole months since shipment."""

    def test_the_tier_boundary_between_twenty_four_and_twenty_five_months(self, api):
        """A claim at exactly 24 months keeps 0.60; one at 25 months drops to 0.30.

        The stamped age is the number of whole months from the package's actual
        ship date to the logical clock at claim creation, with any partial month
        discarded, and the coverage factor is chosen from that stamped age: 1.00
        at 12 months or less, 0.60 above 12 and at most 24, and 0.30 above 24 and
        at most 36.  A package shipped on 2026-09-15 and claimed on 2028-09-15 is
        therefore exactly 24 whole months old and stays on the 0.60 band because
        the upper edge is inclusive, while the same package claimed a month later
        is 25 months old and falls to 0.30.  Both values are frozen at submission
        and neither claim carries a determination or a settlement yet.

        Design: Corner/calculations/warranty_coverage_factor_tier_boundary_at_twenty_four_and_twenty_five_months
        """
        ctx = X.setup_shipped_package(api)
        assert ctx["package"]["actual_ship_date"].startswith("2026-09-15")

        field_data = {
            "as_found_flow_m3h": 300.0,
            "as_found_head_m": 66.0,
            "as_found_npsha_m": 5.50,
            "as_found_solids_pct": 0.0,
            "as_found_viscosity_cst": 1.2,
            "as_found_speed_rpm": 2950,
        }
        lines = [F.claim_line("CL-1", "PARTS", 1205.00)]

        X.set_clock(api, "2028-09-15T00:00:00Z")
        at_edge = validate_success(
            api.create_warranty_claim(
                F.warranty_claim_payload(
                    ctx["package"]["id"], claim_lines=lines, **field_data
                ),
                APPLICATION_ENGINEER,
            ),
            201,
        )

        X.set_clock(api, "2028-10-15T00:00:00Z")
        above_edge = validate_success(
            api.create_warranty_claim(
                F.warranty_claim_payload(
                    ctx["package"]["id"], claim_lines=lines, **field_data
                ),
                APPLICATION_ENGINEER,
            ),
            201,
        )

        assert at_edge["months_since_ship"] == 24
        assert at_edge["coverage_factor"] == pytest.approx(0.60, abs=0.0001)
        assert at_edge["coverage_factor"] == pytest.approx(
            expected_coverage_factor(24), abs=0.0001
        )

        assert above_edge["months_since_ship"] == 25
        assert above_edge["coverage_factor"] == pytest.approx(0.30, abs=0.0001)
        assert above_edge["coverage_factor"] == pytest.approx(
            expected_coverage_factor(25), abs=0.0001
        )

        for claim in (at_edge, above_edge):
            assert claim["status"] == "SUBMITTED"
            assert claim["determination"] is None
            assert claim["settlement_total"] is None

        # The stamped age is never re-derived, so moving the clock on does not
        # revise the earlier claim's tier.
        reread = X.reread_warranty_claim(api, at_edge["id"])
        assert reread["months_since_ship"] == 24
        assert reread["coverage_factor"] == pytest.approx(0.60, abs=0.0001)


# ─────────────────────────────────────────────────────────────────────────────
# Motor requirement
# ─────────────────────────────────────────────────────────────────────────────
def _tested_unit_on_witness_flag(api, world, *, witness_required, serial_suffix):
    """Take one enquiry to a TESTED build order whose run carries `witness_required`.

    The run's witness flag is the only difference between the two branches,
    because that flag is what decides which reference power the package's motor
    requirement is taken from.
    """
    duty = X.create_duty_application(api, witness_required=witness_required)
    selection = get_success_data(
        api.create_selection(
            F.selection_payload(
                duty["id"],
                world["model"]["id"],
                world["config"]["id"],
                duty["version"],
            ),
            APPLICATION_ENGINEER,
        )
    )
    get_success_data(api.propose_selection(selection["id"], APPLICATION_ENGINEER))
    get_success_data(api.approve_selection(selection["id"], HYDRAULIC_APPROVER))

    build_order = get_success_data(
        api.create_build_order(
            F.build_order_payload(
                selection["id"], world["lot"]["id"], serial_number=f"SN-{serial_suffix}"
            ),
            PRODUCTION_PLANNER,
        )
    )
    get_success_data(
        api.record_assembly(build_order["id"], F.assembly_payload(), PRODUCTION_PLANNER)
    )
    run = X.setup_certified_test_run(
        api, build_order["id"], witness_required=witness_required
    )
    return {
        "selection": X.reread_selection(api, selection["id"]),
        "build_order": X.reread_build_order(api, build_order["id"]),
        "test_run": run,
    }


class TestMotorRequirement:
    """The witness flag on the named run chooses the reference power."""

    def test_a_witnessed_run_sizes_the_motor_on_tested_power(self, api, planner_headers):
        """The witnessed package takes 67.21 kW tested power, the other 65.96 kW.

        The motor requirement is fixed at package creation and depends on the
        witness flag of the named test run: when the run is witnessed the minimum
        motor rating is the run's power at the guarantee point multiplied by the
        ten percent motor margin, and when it is not, that same margin is applied
        to the selection's predicted shaft power instead.  The witnessed run here
        measured 67.21 kW at the guarantee point, so its package needs at least
        73.93 kW, while the unwitnessed one falls back on the predicted 65.96 kW
        and needs only 72.56 kW.  The supplied 75.0 kW clears both, both packages
        are created CONFIGURED, and neither carries a guarantee basis yet because
        that is only fixed at release.

        Design: Corner/calculations/motor_requirement_uses_tested_power_when_the_run_is_witnessed
        """
        world = X.setup_master_data(api)
        world["lot"] = X.setup_accepted_lot(api, world, qty_poured=6)
        witnessed = _tested_unit_on_witness_flag(
            api, world, witness_required=True, serial_suffix="0001"
        )
        unwitnessed = _tested_unit_on_witness_flag(
            api, world, witness_required=False, serial_suffix="0002"
        )

        assert witnessed["test_run"]["witness_required"] is True
        assert witnessed["test_run"]["power_at_guarantee_kw"] == pytest.approx(
            67.21, abs=0.01
        )
        assert witnessed["selection"]["predicted_shaft_power_kw"] == pytest.approx(
            65.96, abs=0.01
        )
        assert unwitnessed["test_run"]["witness_required"] is False

        witnessed_response = api.create_pump_package(
            F.pump_package_payload(
                witnessed["build_order"]["id"], witnessed["test_run"]["id"]
            ),
            planner_headers,
        )
        witnessed_package = validate_success(witnessed_response, 201)

        unwitnessed_response = api.create_pump_package(
            F.pump_package_payload(
                unwitnessed["build_order"]["id"], unwitnessed["test_run"]["id"]
            ),
            planner_headers,
        )
        unwitnessed_package = validate_success(unwitnessed_response, 201)

        assert witnessed_package["min_motor_kw"] == pytest.approx(73.93, abs=0.01)
        assert witnessed_package["min_motor_kw"] == pytest.approx(
            round_half_up(67.21 * K.MOTOR_MARGIN, 2), abs=0.01
        )
        # The predicted-power branch belongs to the unwitnessed run only.
        assert witnessed_package["min_motor_kw"] != pytest.approx(72.56, abs=0.005)

        assert unwitnessed_package["min_motor_kw"] == pytest.approx(72.56, abs=0.01)
        assert unwitnessed_package["min_motor_kw"] == pytest.approx(
            round_half_up(65.96 * K.MOTOR_MARGIN, 2), abs=0.01
        )

        for package in (witnessed_package, unwitnessed_package):
            assert package["motor_kw"] == pytest.approx(75.0, abs=0.01)
            assert package["status"] == "CONFIGURED"
            assert package["guarantee_basis"] is None
            assert package["application_error_flagged"] is False


# ─────────────────────────────────────────────────────────────────────────────
# The interpolated guarantee point
# ─────────────────────────────────────────────────────────────────────────────
class TestGuaranteePointInterpolation:
    """Reported values are rounded as produced, and interpolation runs on those."""

    def test_half_up_applies_to_the_reported_points_and_again_to_the_interpolants(
        self, api, test_engineer_headers
    ):
        """A guarantee flow exactly midway lands both interpolants on a half.

        Each reported point value is rounded half up to two decimals as it is
        produced, the reported set is sorted by reported flow, and interpolation
        then runs on those already-rounded values over the single bracketing
        segment with the interpolation fraction held unrounded.  Testing at rated
        speed forces the speed factor to exactly 1, so the reported curve is the
        measured curve, and the 265.0 guarantee flow sits midway between the
        250.0 and 280.0 points for a fraction of exactly 0.5: the head
        interpolates to 74.075 and rounds half up to 74.08, the power to 66.975
        and rounds to 66.98, and the efficiency is then computed from those
        already-rounded values as 79.84 percent.  Truncating instead of rounding
        half up would report 74.07 and 66.97 and a head deviation of 0.14 rather
        than 0.15 percent.

        Design: Corner/calculations/guarantee_point_interpolated_on_rounded_reported_values_with_half_up_at_both_steps
        """
        ctx = X.setup_assembled_build_order(api)
        run = X.setup_locked_test_run(
            api, ctx["build_order"]["id"], points=BRACKETING_CURVE_POINTS
        )

        response = api.evaluate_test_run(run["id"], test_engineer_headers)
        evaluated = validate_success(response, 200)

        assert evaluated["speed_ratio"] == pytest.approx(1.0, abs=0.0001)
        assert evaluated["head_at_guarantee_m"] == pytest.approx(74.08, abs=0.005)
        assert evaluated["head_at_guarantee_m"] != pytest.approx(74.07, abs=0.005)
        assert evaluated["power_at_guarantee_kw"] == pytest.approx(66.98, abs=0.005)
        assert evaluated["power_at_guarantee_kw"] != pytest.approx(66.97, abs=0.005)
        assert evaluated["efficiency_at_guarantee_pct"] == pytest.approx(
            79.84, abs=0.005
        )
        assert evaluated["head_deviation_pct"] == pytest.approx(0.15, abs=0.005)
        assert evaluated["head_deviation_pct"] != pytest.approx(0.14, abs=0.005)
        assert evaluated["efficiency_deviation_pct"] == pytest.approx(-1.38, abs=0.005)
        assert evaluated["npshr_tested_m"] == pytest.approx(3.40, abs=0.01)
        assert_run_dimensions(evaluated, "EVALUATED", "WITHIN_TOLERANCE", "VERIFIED")
