"""Stock items: valuation bases, derived status, duplicate key, adjust
guards, strike reclaim, inventory reconciliation."""
import pytest

from test_helpers import (
    ADMIN,
    EST,
    ApiErrorId,
    assert_stock_item,
    create_stock_item_payload,
    create_takeoff_payload,
    drive_to_loaded_in,
    get_success_data,
    setup_accepted_production,
    setup_basic_scenario,
    setup_in_build_production,
    setup_shop,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestStockValuationDualBasis:
    def test_reuse_vs_replacement_basis_diverge(self, api):
        """PRD §3.7: "`reuse_value_cents` is `quantity_on_hand` multiplied by
        `reuse_unit_cost_cents` (the recovery basis); and
        `replacement_value_cents` is `quantity_on_hand` multiplied by
        `replacement_cost_cents` (the replacement basis, which exceeds the
        recovery basis for every grade since every factor lies below 10000
        bp)."

        Design: Difficulty/dual_variant_calc/stock_valuation_replacement_vs_recovery
        """
        shop = setup_shop()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "B", "quantity_on_hand": 10,
             "replacement_cost_cents": 5000},
            ADMIN,
        ))
        assert_stock_item(si)
        assert si["reuse_unit_cost_cents"] == 2000       # 5000 * 4000bp
        assert si["reuse_value_cents"] == 20000          # 10 * 2000
        assert si["replacement_value_cents"] == 50000    # 10 * 5000
        assert si["reuse_value_cents"] != si["replacement_value_cents"]

    def test_shop_inventory_value_uses_recovery_basis(self, api):
        """PRD §3.7: "The shop's `inventory_value_cents` is the sum of
        `reuse_value_cents` over all its items regardless of status —
        depleted items contribute zero."

        Design: Difficulty/dual_variant_calc/stock_valuation_replacement_vs_recovery
        """
        shop = setup_shop()
        get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "B", "quantity_on_hand": 10,
             "replacement_cost_cents": 5000},
            ADMIN,
        ))
        shop_after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_after["inventory_value_cents"] == 20000


class TestStockCreationDerivedStatus:
    def test_zero_quantity_starts_depleted_positive_starts_active(self, api):
        """PRD §3.7: "An item's `status` is system-managed: `ACTIVE` exactly
        when `quantity_on_hand` is greater than zero, `DEPLETED` exactly when
        it is zero."

        Design: Corner/state_machines/stock_item_created_at_zero_starts_depleted
        """
        shop = setup_shop()
        si_zero = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 0,
             "replacement_cost_cents": 3000},
            ADMIN,
        ))
        si_pos = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "STEEL_TUBE",
             "condition_grade": "A", "quantity_on_hand": 5,
             "replacement_cost_cents": 12000},
            ADMIN,
        ))
        assert si_zero["status"] == "DEPLETED"
        assert si_pos["status"] == "ACTIVE"


class TestStockValidation:
    def test_invalid_condition_grade_returns_400(self, api):
        """PRD §3.7: "`condition_grade` (`A`, `B`, or `C`)". PRD §3.2:
        "supplying an invalid enum value ... is rejected with
        `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/create_stock_item_invalid_enum_returns_400
        """
        shop = setup_shop()
        resp = api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "D", "quantity_on_hand": 10,
             "replacement_cost_cents": 5000},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_duplicate_stock_item_key_returns_409(self, api):
        """PRD §3.7: "the combination of `shop_id`, `material_code`, and
        `condition_grade` must be unique among the shop's items, else
        `ERR_DUPLICATE_STOCK_ITEM` (HTTP 409)."

        Design: Corner/errors/duplicate_stock_item_key_returns_409
        """
        shop = setup_shop()
        get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 10,
             "replacement_cost_cents": 3000},
            ADMIN,
        ))
        # Duplicate triple
        dup = api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 5,
             "replacement_cost_cents": 3100},
            ADMIN,
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_STOCK_ITEM, 409)
        # Different grade on same material is fine
        ok = api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "B", "quantity_on_hand": 5,
             "replacement_cost_cents": 5000},
            ADMIN,
        )
        assert validate_success(ok, expected_status=201)["status"] == "ACTIVE"


class TestStockAdjust:
    def test_adjust_below_zero_rejected(self, api):
        """PRD §3.7: "it increments the item's `version` by 1 and must never
        drive `quantity_on_hand` below zero — a result below zero is rejected
        with `ERR_STOCK_NEGATIVE` (HTTP 409)."

        Design: Corner/validations/stock_adjust_below_zero_returns_409
        """
        shop = setup_shop()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 30,
             "replacement_cost_cents": 3000},
            ADMIN,
        ))
        resp = api.adjust_stock_item(
            si["id"],
            {"delta_quantity": -50, "expected_stock_item_version": si["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STOCK_NEGATIVE, 409)
        after = get_success_data(api.get_stock_item(si["id"], ADMIN))
        assert after["quantity_on_hand"] == 30
        assert after["version"] == si["version"]


class TestStrikeReclaim:
    def test_strike_reclaim_cascade_restores_stock_and_inventory_value(self, api):
        """PRD §3.7: "For each line the system finds the stock item of the
        production's shop matching that `material_code` and `condition_grade`
        — of any origin — or creates one when none matches, with `origin`
        `RECLAIMED`, `quantity_on_hand` starting at 0, and the line's
        `replacement_cost_cents`; the line's quantity is then added to the
        item's `quantity_on_hand`. Every touched item whose quantity leaves
        zero flips `DEPLETED → ACTIVE`, and the shop's
        `inventory_value_cents` is recomputed after all lines have applied."

        Design: Difficulty/transitive_cascade/strike_reclaim_cascade_restores_stock_and_inventory_value
        """
        shop, client, _, _, production, _rev, _res = setup_in_build_production()
        # Pre-existing DEPLETED lumber item
        si_lumber = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "B", "quantity_on_hand": 0,
             "replacement_cost_cents": 5000},
            ADMIN,
        ))
        assert si_lumber["status"] == "DEPLETED"
        # Drive to LOADED_IN
        production, plan = drive_to_loaded_in(shop, client, production)
        # Strike with two reclaim lines
        resp = api.strike(
            production["id"],
            {"reclaim_lines": [
                {"material_code": "LUMBER_4X8", "quantity": 10,
                 "condition_grade": "B", "replacement_cost_cents": 5000},
                {"material_code": "PAINT_GAL", "quantity": 5,
                 "condition_grade": "C", "replacement_cost_cents": 7500},
            ]},
            # need foreman
            __import__("test_helpers").FOREMAN,
        )
        struck = validate_success(resp)
        assert struck["status"] == "STRUCK"
        # Lumber item matched and incremented
        lumber_after = get_success_data(api.get_stock_item(si_lumber["id"], ADMIN))
        assert lumber_after["quantity_on_hand"] == 10
        assert lumber_after["status"] == "ACTIVE"
        # New RECLAIMED paint item created with qty 5
        data, _ = validate_paginated(api.list_stock_items(
            ADMIN, params={"shop_id": shop["id"], "material_code": "PAINT_GAL"},
        ))
        assert len(data) == 1
        assert data[0]["origin"] == "RECLAIMED"
        assert data[0]["quantity_on_hand"] == 5
        # Inventory value: 10*2000 + 5*round_half_up(7500*0.25)=20000+5*1875=29375
        shop_after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_after["inventory_value_cents"] == 29375
        # Earlier plan was executed by load-in
        assert plan["status"] == "EXECUTED"

    def test_strike_creates_reclaimed_item_with_recovery_value(self, api):
        """PRD §3.7: "or creates one when none matches, with `origin`
        `RECLAIMED`, `quantity_on_hand` starting at 0, and the line's
        `replacement_cost_cents`."

        Design: Difficulty/transitive_cascade/strike_reclaim_cascade_restores_stock_and_inventory_value
        """
        shop, client, _, _, production, _rev, _res = setup_in_build_production()
        production, _plan = drive_to_loaded_in(shop, client, production)
        from test_helpers import FOREMAN
        api.strike(production["id"], {"reclaim_lines": [
            {"material_code": "PAINT_GAL", "quantity": 5,
             "condition_grade": "C", "replacement_cost_cents": 7500},
        ]}, FOREMAN)
        data, _ = validate_paginated(api.list_stock_items(
            ADMIN, params={"shop_id": shop["id"], "origin": "RECLAIMED"},
        ))
        assert len(data) == 1
        item = data[0]
        assert item["origin"] == "RECLAIMED"
        assert item["quantity_on_hand"] == 5
        # reuse unit = round_half_up(7500 * 2500bp / 10000) = 1875
        assert item["reuse_unit_cost_cents"] == 1875
        assert item["reuse_value_cents"] == 5 * 1875


class TestInventoryReconciliation:
    def test_inventory_value_tracks_each_mutation(self, api):
        """PRD §3.7: "The shop's `inventory_value_cents` is the sum of
        `reuse_value_cents` over all its items regardless of status — and is
        folded back onto the shop on every quantity mutation."

        Design: Corner/cross_cutting_layers/inventory_value_reconciles_on_adjust_and_consume
        """
        shop, client, pkg = setup_basic_scenario()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 10,
             "replacement_cost_cents": 3000},
            ADMIN,
        ))
        # After create: 10 * 1800 = 18000 (A factor 6000bp)
        after_create = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert after_create["inventory_value_cents"] == 18000
        # +5 adjust
        api.adjust_stock_item(
            si["id"],
            {"delta_quantity": 5, "expected_stock_item_version": si["version"]},
            ADMIN,
        )
        after_adjust = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert after_adjust["inventory_value_cents"] == 27000  # 15*1800
        # STOCK line consume 10
        to = get_success_data(api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10}, EST,
        ))
        api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "LUMBER_4X8", "quantity": 10, "source": "STOCK",
             "stock_item_id": si["id"]},
            EST,
        )
        after_consume = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert after_consume["inventory_value_cents"] == 9000  # 5*1800
