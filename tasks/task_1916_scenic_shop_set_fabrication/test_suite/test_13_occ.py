"""Optimistic concurrency control on Production, Takeoff, and StockItem
versions. PRD §2.8."""
import pytest

from test_helpers import (
    ADMIN,
    EST,
    ApiErrorId,
    get_success_data,
    setup_accepted_production,
    setup_basic_scenario,
    setup_shop,
    supersede_package_to_revision_2,
    validate_error,
    validate_success,
)


class TestStaleProductionVersion:
    def test_change_order_create_with_stale_version_returns_412(self, api):
        """PRD §2.8: "Creating a change order requires
        `expected_production_version`, matched against the target
        production's current `version`; a mismatch is rejected with
        `ERR_STALE_PRODUCTION_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_change_order_stale_version_returns_412
        """
        _, _, _, _, production = setup_accepted_production()
        supersede_package_to_revision_2(production["client_id"])
        prod_now = get_success_data(api.get_production(production["id"], EST))
        v = prod_now["version"]
        # First CO create bumps production.version
        ok = api.create_change_order(
            {"production_id": production["id"],
             "expected_production_version": v,
             "new_drawing_revision": 2, "delta_materials_cents": 0,
             "delta_labor_hours": 5, "delta_load_in_days": 0},
            EST,
        )
        assert validate_success(ok, expected_status=201)["status"] == "PROPOSED"
        # Second create replaying the stale version fails
        resp = api.create_change_order(
            {"production_id": production["id"],
             "expected_production_version": v,
             "new_drawing_revision": 2, "delta_materials_cents": 2000,
             "delta_labor_hours": 6, "delta_load_in_days": 1},
            EST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PRODUCTION_VERSION, 412)

    def test_change_order_create_with_refreshed_version_succeeds(self, api):
        """PRD §2.8: "If the declared value does not equal the parent
        entity's current `version`, the request is rejected with the
        corresponding stale-version error — HTTP 412 in every case — and no
        mutation occurs."

        Design: Corner/cross_cutting_layers/occ_change_order_stale_version_returns_412
        """
        _, _, _, _, production = setup_accepted_production()
        supersede_package_to_revision_2(production["client_id"])
        prod_now = get_success_data(api.get_production(production["id"], EST))
        v = prod_now["version"]
        api.create_change_order(
            {"production_id": production["id"],
             "expected_production_version": v,
             "new_drawing_revision": 2, "delta_materials_cents": 0,
             "delta_labor_hours": 5, "delta_load_in_days": 0},
            EST,
        )
        # Re-read, then create succeeds
        prod_fresh = get_success_data(api.get_production(production["id"], EST))
        ok = api.create_change_order(
            {"production_id": production["id"],
             "expected_production_version": prod_fresh["version"],
             "new_drawing_revision": 2, "delta_materials_cents": 2000,
             "delta_labor_hours": 6, "delta_load_in_days": 1},
            EST,
        )
        co_2 = validate_success(ok, expected_status=201)
        assert co_2["status"] == "PROPOSED"
        assert co_2["co_no"] == 2


class TestStaleTakeoffVersion:
    def test_takeoff_line_add_with_stale_version_returns_412(self, api):
        """PRD §2.8: "Adding a takeoff line requires
        `expected_takeoff_version`, matched against the target takeoff's
        current `version`; a mismatch is rejected with
        `ERR_STALE_TAKEOFF_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_takeoff_line_stale_version_returns_412
        """
        _, _, pkg = setup_basic_scenario()
        to = get_success_data(api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10}, EST,
        ))
        # Line 1 succeeds (bumps takeoff version)
        api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "LUMBER_4X8", "quantity": 2, "source": "PURCHASE",
             "unit_cost_cents": 5000},
            EST,
        )
        # Replay stale version on second add
        resp = api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "PAINT_GAL", "quantity": 1, "source": "PURCHASE",
             "unit_cost_cents": 7500},
            EST,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_TAKEOFF_VERSION, 412)

    def test_stale_takeoff_add_does_not_mutate_subtotal(self, api):
        """PRD §2.8: "the request is rejected with the corresponding
        stale-version error — HTTP 412 in every case — and no mutation
        occurs."

        Design: Corner/cross_cutting_layers/occ_takeoff_line_stale_version_returns_412
        """
        _, _, pkg = setup_basic_scenario()
        to = get_success_data(api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10}, EST,
        ))
        api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "LUMBER_4X8", "quantity": 2, "source": "PURCHASE",
             "unit_cost_cents": 5000},
            EST,
        )
        api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "PAINT_GAL", "quantity": 1, "source": "PURCHASE",
             "unit_cost_cents": 7500},
            EST,
        )
        after = get_success_data(api.get_takeoff(to["id"], EST))
        assert after["materials_subtotal_cents"] == 10000  # 2 * 5000


class TestStaleStockVersion:
    def test_adjust_with_stale_version_returns_412(self, api):
        """PRD §2.8: "Adjusting a stock item requires
        `expected_stock_item_version`, matched against the item's current
        `version`; a mismatch is rejected with `ERR_STALE_STOCK_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stock_adjust_stale_version_returns_412
        """
        shop = setup_shop()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 30,
             "replacement_cost_cents": 3000},
            ADMIN,
        ))
        # First adjust bumps version
        api.adjust_stock_item(
            si["id"],
            {"delta_quantity": 5, "expected_stock_item_version": si["version"]},
            ADMIN,
        )
        # Replay stale version
        resp = api.adjust_stock_item(
            si["id"],
            {"delta_quantity": 5, "expected_stock_item_version": si["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_STOCK_VERSION, 412)

    def test_adjust_increments_version_by_one(self, api):
        """PRD §3.7: "it increments the item's `version` by 1". PRD §2.8:
        the OCC check is the mechanism.

        Design: Corner/cross_cutting_layers/occ_stock_adjust_stale_version_returns_412
        """
        shop = setup_shop()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 30,
             "replacement_cost_cents": 3000},
            ADMIN,
        ))
        ok = api.adjust_stock_item(
            si["id"],
            {"delta_quantity": 5, "expected_stock_item_version": si["version"]},
            ADMIN,
        )
        after = validate_success(ok)
        assert after["quantity_on_hand"] == 35
        assert after["version"] == si["version"] + 1
