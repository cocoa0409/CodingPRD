"""Boundary-precision supplements: safety factor at 1.50 (second test),
stock decrement-to-zero (second test), change-order pricing with posture
branch (second test)."""
import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    EST,
    FOREMAN,
    ApiErrorId,
    create_rom_bid,
    create_change_order_on_production,
    get_success_data,
    setup_accepted_production,
    setup_basic_scenario,
    setup_shop,
    submit_bid,
    accept_bid,
    supersede_package_to_revision_2,
    validate_error,
    validate_success,
)


class TestSafetyFactorBoundaryNegative:
    def test_sf_below_one_five_fails(self, api):
        """PRD §3.4: "the static factor must be at least 1.50 (a value of
        exactly 1.50 passes) ... failing with `ERR_SAFETY_FACTOR_INSUFFICIENT`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/safety_factor_exactly_one_five_passes
        """
        _, _, _, _, production = setup_accepted_production()
        # PRD §3.4 rounds sf_static half-up to two decimals before the 1.50
        # gate: 5979/4000 = 1.49475 -> 1.49 < 1.50 -> fails. (5999/4000 =
        # 1.49975 would round to exactly 1.50 and pass.)
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 5979},
            FOREMAN,
        ))
        resp = api.approve_engineering_review(rev["id"], ENGINEER)
        validate_error(resp, ApiErrorId.ERR_SAFETY_FACTOR_INSUFFICIENT, 422)


class TestStockZeroBoundary:
    def test_consume_to_zero_leaves_item_depleted(self, api):
        """PRD §3.2: "consuming exactly down to zero is allowed. The item's
        `status` flips from `ACTIVE` to `DEPLETED` whenever a mutation leaves
        `quantity_on_hand` at zero, and the shop's `inventory_value_cents` is
        recomputed."

        Design: Difficulty/boundary_precision_check/stock_decrement_to_exactly_zero_depletes
        """
        shop, client, pkg = setup_basic_scenario()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "PAINT_GAL",
             "condition_grade": "A", "quantity_on_hand": 30,
             "replacement_cost_cents": 4000},
            ADMIN,
        ))
        to = get_success_data(api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10}, EST,
        ))
        line_resp = api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "PAINT_GAL", "quantity": 30, "source": "STOCK",
             "stock_item_id": si["id"]},
            EST,
        )
        # Consume exactly to zero -> 201
        line = validate_success(line_resp, expected_status=201)
        assert line["quantity"] == 30
        # Stock flipped to DEPLETED at exactly 0
        si_after = get_success_data(api.get_stock_item(si["id"], ADMIN))
        assert si_after["quantity_on_hand"] == 0
        assert si_after["status"] == "DEPLETED"


class TestChangeOrderPricingPostureBranch:
    def test_open_posture_uses_straight_time_multiplier(self, api):
        """PRD §3.5: "The labor multiplier is the shop's
        `overtime_multiplier_bp` when the posture at creation is `TIGHT` or
        `SATURATED`, and 10000 otherwise."

        Design: Difficulty/combinatorial_formula/change_order_price_posture_branch_with_rush_cap
        """
        # 100 committed on 400 horizon -> 2500bp -> OPEN (no overtime)
        _, _, _, _, production = setup_accepted_production(estimated_crew_hours=100)
        supersede_package_to_revision_2(production["client_id"])
        co = create_change_order_on_production(
            production["id"], new_drawing_revision=2,
            delta_materials_cents=100000, delta_labor_hours=40,
            delta_load_in_days=-3,
        )
        # OPEN: labor = 40*8000*1.0 = 320000; rush min(3000,1500)=1500bp
        #       rush = round(320000*0.15)=48000
        # materials = round(100000*1.10)=110000
        # delta = 110000 + 320000 + 48000 = 478000
        assert co["priced_posture"] == "OPEN"
        assert co["delta_price_cents"] == 478000
