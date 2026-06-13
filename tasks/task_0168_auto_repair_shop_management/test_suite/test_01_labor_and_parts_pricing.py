"""Pricing-engine tests: dual-variant labor charge, dual-variant parts markup,
marginal tier slicing, round-per-line-then-sum, and the markup tier boundary.

Covers difficulty queue rules: dual_variant_calc, combinatorial_formula,
boundary_precision_check (markup tier).
"""
from test_helpers import (
    validate_success,
    fixtures as fx,
)
from test_helpers.test_users import TEST_USERS, make_technician_headers
from test_helpers import factories as f

SM = TEST_USERS["shop_manager_headers"]
PM = TEST_USERS["parts_manager_headers"]


# ===========================================================================
# dual_variant_calc — labor_charge FLAT_RATE vs TIME_AND_MATERIALS
# ===========================================================================
class TestLaborChargeDualVariant:
    def test_flat_rate_line_bills_book_hours(self, api):
        """PRD §3.5: "for a `FLAT_RATE` line the charge is the line's snapshotted
        `book_hours` multiplied by the effective rate, then rounded half up — this
        charge is fixed at line creation, bills the book hours, and never depends
        on actual clocked time."

        Design: Difficulty/dual_variant_calc/labor_charge_flat_rate_vs_time_and_materials
        """
        state = fx.setup_ro_in_progress(
            api,
            op_overrides={"book_hours": 2.0, "default_rate_cents": 12000},
            create_line=False,
            bay_start="2026-06-01T09:00:00Z",
            bay_end="2026-06-01T16:00:00Z",
        )
        operation = fx.create_labor_operation(api, book_hours=2.0, default_rate_cents=12000)
        technician = fx.create_technician(api)
        flat = validate_success(
            api.create_labor_line(
                state["ro"]["id"],
                f.create_labor_line_payload(
                    operation["id"], technician_id=technician["id"], billing_method="FLAT_RATE"
                ),
                SM,
            ),
            201,
        )
        # Even though we clock 1.5h, FLAT_RATE bills book hours 2.0 * 12000 = 24000.
        fx.clock_in(api, flat["id"], technician["id"], "2026-06-01T09:00:00Z")
        fx.clock_out(api, flat["id"], technician["id"], "2026-06-01T10:30:00Z")
        completed = validate_success(
            api.complete_labor_line(flat["id"], make_technician_headers(technician["id"])), 200
        )
        assert completed["charge_cents"] == 24000, (
            f"FLAT_RATE charge must be book_hours*rate=24000, got {completed['charge_cents']}"
        )

    def test_time_and_materials_line_bills_actual_hours(self, api):
        """PRD §3.5: "For a `TIME_AND_MATERIALS` line the charge is instead the
        line's accumulated `actual_hours` multiplied by the effective rate, then
        rounded half up — it bills the actual clocked hours and ignores the book
        hours; it is zero until the first clock-out, provisional while work
        proceeds, and final at completion."

        Design: Difficulty/dual_variant_calc/labor_charge_flat_rate_vs_time_and_materials
        """
        state = fx.setup_ro_in_progress(
            api,
            op_overrides={"book_hours": 2.0, "default_rate_cents": 12000},
            create_line=False,
            bay_start="2026-06-01T09:00:00Z",
            bay_end="2026-06-01T16:00:00Z",
        )
        operation = fx.create_labor_operation(api, book_hours=2.0, default_rate_cents=12000)
        technician = fx.create_technician(api)
        tm = validate_success(
            api.create_labor_line(
                state["ro"]["id"],
                f.create_labor_line_payload(
                    operation["id"],
                    technician_id=technician["id"],
                    billing_method="TIME_AND_MATERIALS",
                ),
                SM,
            ),
            201,
        )
        fx.clock_in(api, tm["id"], technician["id"], "2026-06-01T10:45:00Z")
        fx.clock_out(api, tm["id"], technician["id"], "2026-06-01T12:15:00Z")
        completed = validate_success(
            api.complete_labor_line(tm["id"], make_technician_headers(technician["id"])), 200
        )
        # T&M bills actual hours 1.5 * 12000 = 18000, ignoring book 2.0.
        assert completed["charge_cents"] == 18000, (
            f"T&M charge must be actual_hours*rate=18000, got {completed['charge_cents']}"
        )


# ===========================================================================
# dual_variant_calc — parts_markup MARGINAL vs FLAT_BRACKET
# ===========================================================================
class TestPartsMarkupDualVariant:
    def test_marginal_mode_slices_cost_across_bands(self, api):
        """PRD §3.5: "Under `MARGINAL` mode, the per-unit cost is instead sliced
        across the bands ... each positive slice contributes that slice multiplied
        by one plus the tier's `markup_pct`, rounded half up per slice, accumulated
        into the per-unit sell price."

        Design: Difficulty/dual_variant_calc/parts_markup_marginal_vs_flat_bracket
        """
        fx.setup_three_tier_matrix(api)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        pl = validate_success(
            api.create_part_line(
                ro["id"],
                f.create_part_line_payload("P-MG", 2, 8000, markup_mode="MARGINAL"),
                PM,
            ),
            201,
        )
        # cost 8000 sliced: 5000*1.5 + 3000*1.4 = 7500 + 4200 = 11700/unit; *2 = 23400.
        assert pl["extended_charge_cents"] == 23400

    def test_flat_bracket_mode_marks_whole_cost_at_containing_tier(self, api):
        """PRD §3.5: "Under `FLAT_BRACKET` mode, the entire per-unit cost is marked
        up at the single tier whose band contains that cost ... the per-unit sell
        price is the per-unit cost multiplied by one plus that tier's `markup_pct`,
        rounded half up."

        Design: Difficulty/dual_variant_calc/parts_markup_marginal_vs_flat_bracket
        """
        fx.setup_three_tier_matrix(api)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        pl = validate_success(
            api.create_part_line(
                ro["id"],
                f.create_part_line_payload("P-FB", 2, 8000, markup_mode="FLAT_BRACKET"),
                PM,
            ),
            201,
        )
        # cost 8000 in [5000,20000)@0.40: 8000*1.4 = 11200/unit; *2 = 22400.
        assert pl["extended_charge_cents"] == 22400


# ===========================================================================
# combinatorial_formula — marginal tier selection over 3 inputs
# ===========================================================================
class TestMarginalTierSelection:
    def test_marginal_slices_cost_then_multiplies_quantity(self, api):
        """PRD §3.5: "the slice is the portion of the cost interval from zero up to
        the per-unit cost that overlaps the tier's band — concretely the amount by
        which the smaller of the per-unit cost and the band's upper bound exceeds
        the band's lower bound, floored at zero ... In both modes the line's
        `extended_charge_cents` is the resulting per-unit sell price multiplied by
        the line `quantity`."

        Design: Difficulty/combinatorial_formula/parts_markup_marginal_tier_selection_three_inputs
        """
        fx.setup_three_tier_matrix(api)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        pl = validate_success(
            api.create_part_line(
                ro["id"],
                f.create_part_line_payload("P-SLICE", 2, 8000, markup_mode="MARGINAL"),
                PM,
            ),
            201,
        )
        assert pl["extended_charge_cents"] == 23400

    def test_marginal_single_band_cost_within_first_tier(self, api):
        """PRD §3.5: "each positive slice contributes that slice multiplied by one
        plus the tier's `markup_pct`, rounded half up per slice, accumulated into
        the per-unit sell price."

        Design: Difficulty/combinatorial_formula/parts_markup_marginal_tier_selection_three_inputs
        """
        fx.setup_three_tier_matrix(api)
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        pl = validate_success(
            api.create_part_line(
                ro["id"],
                f.create_part_line_payload("P-ONEBAND", 3, 4000, markup_mode="MARGINAL"),
                PM,
            ),
            201,
        )
        # cost 4000 wholly inside [0,5000)@0.50: 4000*1.5 = 6000/unit; *3 = 18000.
        assert pl["extended_charge_cents"] == 18000


# ===========================================================================
# combinatorial_formula — round-per-line-then-sum
# ===========================================================================
class TestRoundPerLineThenSum:
    def test_two_lines_round_individually_before_summing(self, api):
        """PRD §2.7: "each individual line is rounded first, and only then are the
        rounded line amounts summed."
        PRD §3.6: "The `parts_total_cents` is the sum of the already-rounded
        `extended_charge_cents` over the order's part lines whose status is not
        `RETURNED`."

        Design: Difficulty/combinatorial_formula/repair_order_total_round_per_line_then_sum
        """
        fx.setup_markup_matrix(api, [(0, 0, 5000, 0.50)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        # Each line: cost 333 * 1.5 = 499.5 -> round_half_up 500.
        validate_success(
            api.create_part_line(
                ro["id"], f.create_part_line_payload("P-R1", 1, 333, markup_mode="MARGINAL"), PM
            ),
            201,
        )
        validate_success(
            api.create_part_line(
                ro["id"], f.create_part_line_payload("P-R2", 1, 333, markup_mode="MARGINAL"), PM
            ),
            201,
        )
        ro_now = validate_success(api.get_repair_order(ro["id"], SM), 200)
        # 500 + 500 = 1000 (round-per-line); sum-then-round would give 999.
        assert ro_now["parts_total_cents"] == 1000, (
            f"parts_total must be 1000 (round-per-line), got {ro_now['parts_total_cents']}"
        )
        assert ro_now["grand_total_cents"] == 1000

    def test_single_line_rounds_half_up(self, api):
        """PRD §2.7: "Wherever a rounding step is called for, the system uses the
        **round-half-up** method to the nearest whole cent."

        Design: Difficulty/combinatorial_formula/repair_order_total_round_per_line_then_sum
        """
        fx.setup_markup_matrix(api, [(0, 0, 5000, 0.50)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        pl = validate_success(
            api.create_part_line(
                ro["id"], f.create_part_line_payload("P-R1", 1, 333, markup_mode="MARGINAL"), PM
            ),
            201,
        )
        # 333*1.5 = 499.5 -> 500.
        assert pl["extended_charge_cents"] == 500


# ===========================================================================
# boundary_precision_check — markup tier inclusive lower bound
# ===========================================================================
class TestMarkupTierBoundary:
    def test_cost_just_below_boundary_uses_lower_tier(self, api):
        """PRD §3.5: "the tier whose `lower_bound_cents` is less than or equal to
        the per-unit cost and whose `upper_bound_cents` (treated as positive
        infinity when null) is strictly greater than it; the per-unit sell price is
        the per-unit cost multiplied by one plus that tier's `markup_pct`, rounded
        half up."

        Design: Difficulty/boundary_precision_check/markup_tier_boundary_at_exact_lower_bound
        """
        fx.setup_markup_matrix(api, [(0, 0, 5000, 0.50), (1, 5000, 20000, 0.40)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        pl = validate_success(
            api.create_part_line(
                ro["id"],
                f.create_part_line_payload("BD-4999", 1, 4999, markup_mode="FLAT_BRACKET"),
                PM,
            ),
            201,
        )
        # 4999 in [0,5000)@0.50: 4999*1.5 = 7498.5 -> 7499.
        assert pl["extended_charge_cents"] == 7499

    def test_cost_at_exact_lower_bound_uses_higher_tier(self, api):
        """PRD §3.5: "the tier whose `lower_bound_cents` is less than or equal to
        the per-unit cost and whose `upper_bound_cents` (treated as positive
        infinity when null) is strictly greater than it; the per-unit sell price is
        the per-unit cost multiplied by one plus that tier's `markup_pct`, rounded
        half up."

        Design: Difficulty/boundary_precision_check/markup_tier_boundary_at_exact_lower_bound
        """
        fx.setup_markup_matrix(api, [(0, 0, 5000, 0.50), (1, 5000, 20000, 0.40)])
        customer, vehicle = fx.create_customer_and_vehicle(api)
        ro = fx.create_repair_order(api, customer["id"], vehicle["id"], tax_rate=0.0)
        pl = validate_success(
            api.create_part_line(
                ro["id"],
                f.create_part_line_payload("BD-5000", 1, 5000, markup_mode="FLAT_BRACKET"),
                PM,
            ),
            201,
        )
        # 5000 in [5000,20000)@0.40 (inclusive lower bound): 5000*1.4 = 7000.
        assert pl["extended_charge_cents"] == 7000
