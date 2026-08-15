"""Bid pricing: ROM vs DETAILED variants, per-line rounding, volume tier,
reuse credit. Covers dual_variant_calc and combinatorial_formula rules."""
import pytest

from test_helpers import (
    ADMIN,
    EST,
    ApiErrorId,
    assert_bid,
    assert_takeoff,
    create_rom_bid,
    get_success_data,
    make_client_pm_headers,
    setup_basic_scenario,
    setup_shop,
    setup_client,
    setup_design_package,
    validate_error,
    validate_success,
)


def _create_takeoff_with_lines(api, pkg_id, labor_hours, lines):
    """Helper: open a takeoff and add lines sequentially (OCC respected)."""
    to = get_success_data(api.create_takeoff(
        {"design_package_id": pkg_id, "labor_hours_est": labor_hours}, EST,
    ))
    version = to["version"]
    last_line = None
    for ln in lines:
        payload = dict(ln)
        payload["takeoff_id"] = to["id"]
        payload["expected_takeoff_version"] = version
        last_line = get_success_data(api.create_takeoff_line(payload, EST))
        version = get_success_data(api.get_takeoff(to["id"], EST))["version"]
    return to, last_line


class TestDualVariantPricing:
    def test_detailed_bid_price_computation(self, api):
        """PRD §3.3: "Detailed pricing walks a pinned evaluation order, with
        round-half-up to integer cents at every step. ... the gross materials
        cost is the sum of those per-line totals. ... the labor cost is the
        takeoff's `labor_hours_est` multiplied by the shop's
        `labor_rate_cents_per_hour`. ... the final `price_cents` is base plus
        overhead plus margin."

        Design: Difficulty/dual_variant_calc/bid_price_rom_vs_detailed_same_package
        """
        shop, client, pkg = setup_basic_scenario(load_in_at="2026-08-29T00:00:00Z")
        to, _line = _create_takeoff_with_lines(api, pkg["id"], 100, [
            {"material_code": "LUMBER_4X8", "quantity": 28, "source": "PURCHASE",
             "unit_cost_cents": 5000},
        ])
        resp = api.create_bid(
            {
                "client_id": client["id"], "design_package_id": pkg["id"],
                "pricing_variant": "DETAILED", "takeoff_id": to["id"],
                "has_automation_scope": False, "bays_required": 1,
                "build_start_at": "2026-08-05T00:00:00Z", "validity_days": 30,
            },
            EST,
        )
        bid = validate_success(resp, expected_status=201)
        # materials 28*5000 = 140000; labor 100*8000 = 800000; base 940000;
        # overhead 94000; margin round_half_up(1034000*0.2)=206800; total 1240800
        assert bid["price_cents"] == 1240800, f"got {bid['price_cents']}"
        assert_bid(bid)

    def test_rom_bid_price_computation_with_urgency(self, api):
        """PRD §3.3: "When that figure is at most 28 days, the urgency
        multiplier is 12500 bp; otherwise it is 10000 bp. The price is
        `floor_area_sqft` multiplied by the complexity rate — 9000 cents per
        square foot for `A_SIMPLE`, 14000 for `B_STANDARD`, 22000 for
        `C_COMPLEX` — multiplied by the urgency multiplier, divided by 10000,
        rounded half-up to a whole cent."

        Design: Difficulty/dual_variant_calc/bid_price_rom_vs_detailed_same_package
        """
        shop, client, pkg = setup_basic_scenario(load_in_at="2026-08-29T00:00:00Z")
        bid = create_rom_bid(
            client["id"], pkg["id"],
            floor_area_sqft=200, complexity_class="B_STANDARD",
            build_start_at="2026-08-05T00:00:00Z", estimated_crew_hours=100,
        )
        # 200 * 14000 * 12500/10000 = 3500000 (28 days == urgency window boundary)
        assert bid["price_cents"] == 3500000, f"got {bid['price_cents']}"

    def test_two_variants_diverge_on_same_package(self, api):
        """PRD §3.3: "The same package priced by both variants will generally
        yield two different prices; that divergence is expected."

        Design: Difficulty/dual_variant_calc/bid_price_rom_vs_detailed_same_package
        """
        shop, client, pkg = setup_basic_scenario(load_in_at="2026-08-29T00:00:00Z")
        to, _line = _create_takeoff_with_lines(api, pkg["id"], 100, [
            {"material_code": "LUMBER_4X8", "quantity": 28, "source": "PURCHASE",
             "unit_cost_cents": 5000},
        ])
        bid_det = get_success_data(api.create_bid(
            {
                "client_id": client["id"], "design_package_id": pkg["id"],
                "pricing_variant": "DETAILED", "takeoff_id": to["id"],
                "has_automation_scope": False, "bays_required": 1,
                "build_start_at": "2026-08-05T00:00:00Z", "validity_days": 30,
            },
            EST,
        ))
        bid_rom = create_rom_bid(
            client["id"], pkg["id"],
            floor_area_sqft=200, complexity_class="B_STANDARD",
            build_start_at="2026-08-05T00:00:00Z", estimated_crew_hours=100,
        )
        assert bid_det["price_cents"] == 1240800
        assert bid_rom["price_cents"] == 3500000
        assert bid_det["price_cents"] != bid_rom["price_cents"]


class TestPerLineRoundingOrder:
    def test_line_total_rounds_half_up_per_line(self, api):
        """PRD §3.2: "The line's `line_total_cents` is then `quantity`
        multiplied by `applied_unit_cost_cents`, multiplied by the quantity
        10000 plus `waste_pct_bp`, divided by 10000, rounded half-up to a
        whole cent."

        Design: Difficulty/combinatorial_formula/detailed_bid_per_line_rounding_order
        """
        shop, client, pkg = setup_basic_scenario()
        to, line1 = _create_takeoff_with_lines(api, pkg["id"], 1, [
            {"material_code": "STEEL_TUBE", "quantity": 3, "source": "PURCHASE",
             "unit_cost_cents": 1999, "waste_pct_bp": 1500},
        ])
        # round_half_up(3 * 1999 * 1.15) = round_half_up(6896.55) = 6897
        assert line1["line_total_cents"] == 6897

    def test_subtotal_is_sum_of_per_line_rounded_totals(self, api):
        """PRD §3.2: "The takeoff's `materials_subtotal_cents` is the sum of
        `line_total_cents` over all its lines, recomputed on every line
        addition or removal."  PRD §2.10: "the rounding happens at exactly
        those pinned steps and never on a later aggregate in their place."

        Design: Difficulty/combinatorial_formula/detailed_bid_per_line_rounding_order
        """
        shop, client, pkg = setup_basic_scenario()
        to, _l = _create_takeoff_with_lines(api, pkg["id"], 1, [
            {"material_code": "STEEL_TUBE", "quantity": 3, "source": "PURCHASE",
             "unit_cost_cents": 1999, "waste_pct_bp": 1500},
            {"material_code": "STEEL_TUBE", "quantity": 3, "source": "PURCHASE",
             "unit_cost_cents": 1999, "waste_pct_bp": 1500},
        ])
        takeoff = get_success_data(api.get_takeoff(to["id"], EST))
        # per-line round: 6897 + 6897 = 13794 (sum-then-round would be 13793)
        assert takeoff["materials_subtotal_cents"] == 13794

        bid = get_success_data(api.create_bid(
            {
                "client_id": client["id"], "design_package_id": pkg["id"],
                "pricing_variant": "DETAILED", "takeoff_id": to["id"],
                "has_automation_scope": False, "bays_required": 1,
                "build_start_at": "2026-09-01T00:00:00Z", "validity_days": 30,
            },
            EST,
        ))
        # base 13794+8000=21794; overhead round(21794*0.1)=2179;
        # margin round(23973*0.2)=4795; total 28768
        assert bid["price_cents"] == 28768


class TestReuseCreditTierOnPreDiscountGross:
    def test_stock_line_applied_unit_cost_uses_condition_factor(self, api):
        """PRD §3.2: "For a `STOCK` line, `applied_unit_cost_cents` is the
        referenced item's `replacement_cost_cents` multiplied by the condition
        factor for its `condition_grade` — 6000 bp for grade `A`, 4000 bp for
        grade `B`, 2500 bp for grade `C` — divided by 10000, rounded half-up
        to a whole cent."

        Design: Difficulty/combinatorial_formula/reuse_credit_tier_keyed_on_pre_discount_gross
        """
        shop, client, pkg = setup_basic_scenario()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "B", "quantity_on_hand": 300,
             "replacement_cost_cents": 5000},
            ADMIN,
        ))
        to, line = _create_takeoff_with_lines(api, pkg["id"], 1, [
            {"material_code": "LUMBER_4X8", "quantity": 255, "source": "STOCK",
             "stock_item_id": si["id"]},
        ])
        assert line["applied_unit_cost_cents"] == 2000  # 5000 * 4000bp

    def test_volume_tier_keyed_on_pre_discount_gross(self, api):
        """PRD §3.3: "Third, the volume-discount tier is selected on the
        **pre-discount** gross: if the gross materials cost is at least 500000
        cents, the tier discount is 500 bp, otherwise 0. Keying the tier on
        the discounted subtotal is the forbidden alternative reading — the
        tier test always sees the undiscounted gross."

        Design: Difficulty/combinatorial_formula/reuse_credit_tier_keyed_on_pre_discount_gross
        """
        shop, client, pkg = setup_basic_scenario()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "B", "quantity_on_hand": 300,
             "replacement_cost_cents": 5000},
            ADMIN,
        ))
        to, _line = _create_takeoff_with_lines(api, pkg["id"], 1, [
            {"material_code": "LUMBER_4X8", "quantity": 255, "source": "STOCK",
             "stock_item_id": si["id"]},
        ])
        takeoff = get_success_data(api.get_takeoff(to["id"], EST))
        assert takeoff["materials_subtotal_cents"] == 510000

        bid = get_success_data(api.create_bid(
            {
                "client_id": client["id"], "design_package_id": pkg["id"],
                "pricing_variant": "DETAILED", "takeoff_id": to["id"],
                "has_automation_scope": False, "bays_required": 1,
                "build_start_at": "2026-09-01T00:00:00Z", "validity_days": 30,
            },
            EST,
        ))
        # tier applies at pre-discount gross 510000: materials 484500,
        # labor 8000 -> base 492500; overhead 49250;
        # margin round_half_up(541750*0.2)=108350; total 650100
        assert bid["price_cents"] == 650100

        si_after = get_success_data(api.get_stock_item(si["id"], ADMIN))
        assert si_after["quantity_on_hand"] == 45  # 300 - 255


class TestVolumeTierBoundary:
    def test_gross_exactly_at_tier_applies_discount(self, api):
        """PRD §3.3: "if the gross materials cost is at least 500000 cents,
        the tier discount is 500 bp, otherwise 0."

        Design: Corner/calculations/volume_tier_boundary_exactly_500000_applies
        """
        shop, client, pkg = setup_basic_scenario()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "B", "quantity_on_hand": 600,
             "replacement_cost_cents": 5000},
            ADMIN,
        ))
        to, _line = _create_takeoff_with_lines(api, pkg["id"], 1, [
            {"material_code": "LUMBER_4X8", "quantity": 250, "source": "STOCK",
             "stock_item_id": si["id"]},
        ])
        bid = get_success_data(api.create_bid(
            {
                "client_id": client["id"], "design_package_id": pkg["id"],
                "pricing_variant": "DETAILED", "takeoff_id": to["id"],
                "has_automation_scope": False, "bays_required": 1,
                "build_start_at": "2026-09-01T00:00:00Z", "validity_days": 30,
            },
            EST,
        ))
        # 250 * 2000 = 500000; tier 500bp applies
        # materials 475000; labor 8000; base 483000; overhead 48300;
        # margin round(531300*0.2)=106260; total 637560
        assert bid["price_cents"] == 637560

    def test_gross_one_unit_below_tier_gets_no_discount(self, api):
        """PRD §3.3: "if the gross materials cost is at least 500000 cents,
        the tier discount is 500 bp, otherwise 0."

        Design: Corner/calculations/volume_tier_boundary_exactly_500000_applies
        """
        shop, client, pkg = setup_basic_scenario()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "B", "quantity_on_hand": 600,
             "replacement_cost_cents": 5000},
            ADMIN,
        ))
        to, _line = _create_takeoff_with_lines(api, pkg["id"], 1, [
            {"material_code": "LUMBER_4X8", "quantity": 249, "source": "STOCK",
             "stock_item_id": si["id"]},
        ])
        bid = get_success_data(api.create_bid(
            {
                "client_id": client["id"], "design_package_id": pkg["id"],
                "pricing_variant": "DETAILED", "takeoff_id": to["id"],
                "has_automation_scope": False, "bays_required": 1,
                "build_start_at": "2026-09-01T00:00:00Z", "validity_days": 30,
            },
            EST,
        ))
        # 249 * 2000 = 498000; no tier
        # base 506000; overhead 50600; margin round(556600*0.2)=111320; total 667920
        assert bid["price_cents"] == 667920
