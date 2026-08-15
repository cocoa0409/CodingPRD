"""Takeoffs and takeoff lines: creation defaults, pinning, lock gate,
parent FK existence, reverse reachability, conservation on create/delete."""
import pytest

from test_helpers import (
    ADMIN,
    EST,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_takeoff,
    assert_takeoff_line,
    create_rom_bid,
    create_takeoff_payload,
    get_success_data,
    make_client_pm_headers,
    make_estimator_headers,
    setup_basic_scenario,
    setup_shop,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTakeoffCreation:
    def test_takeoff_created_with_defaults_and_pinned_revision(self, api):
        """PRD §3.2: "The system stamps the takeoff with the creating
        estimator's `X-User-ID` as `estimator_user_id`, pins the package's
        current revision into `pinned_package_revision`, starts
        `materials_subtotal_cents` at 0, and sets the takeoff's `status` to
        `DRAFT`."

        Design: Corner/entities/takeoff_created_with_defaults_and_pinned_revision
        """
        _, _, pkg = setup_basic_scenario()
        resp = api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 40},
            make_estimator_headers("est_1"),
        )
        to = validate_success(resp, expected_status=201)
        assert_takeoff(to)
        assert to["status"] == "DRAFT"
        assert to["materials_subtotal_cents"] == 0
        assert to["pinned_package_revision"] == 1
        assert to["estimator_user_id"] == "est_1"


class TestTakeoffLineParentExistence:
    def test_line_with_nonexistent_takeoff_returns_404(self, api):
        """PRD §2.6 priority 3: "every path identifier and every
        body-referenced identifier (`production_id`, `takeoff_id`,
        `stock_item_id`, `design_package_id`, `client_id`, ...) must resolve
        to an existing resource; the first unresolvable identifier rejects
        the request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/takeoff_line_with_nonexistent_takeoff_returns_404
        """
        _, _, pkg = setup_basic_scenario()
        # Need a well-formed expected_takeoff_version; take it from a real takeoff
        real_to = get_success_data(api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10}, EST,
        ))
        resp = api.create_takeoff_line(
            {"takeoff_id": NON_EXISTENT_UUID,
             "expected_takeoff_version": real_to["version"],
             "material_code": "LUMBER_4X8", "quantity": 5,
             "source": "PURCHASE", "unit_cost_cents": 5000},
            EST,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


class TestTakeoffLockedGate:
    def _setup_locked_takeoff(self, api):
        """Build a takeoff with one line, referenced by a submitted DETAILED bid."""
        _, client, pkg = setup_basic_scenario()
        to = get_success_data(api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10}, EST,
        ))
        get_success_data(api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "LUMBER_4X8", "quantity": 2, "source": "PURCHASE",
             "unit_cost_cents": 5000},
            EST,
        ))
        bid = get_success_data(api.create_bid(
            {"client_id": client["id"], "design_package_id": pkg["id"],
             "pricing_variant": "DETAILED", "takeoff_id": to["id"],
             "has_automation_scope": False, "bays_required": 1,
             "build_start_at": "2026-09-01T00:00:00Z", "validity_days": 30},
            EST,
        ))
        submit_bid(bid["id"])
        return to, client

    def test_add_line_after_lock_fails_with_takeoff_locked(self, api):
        """PRD §3.2: "when a `DETAILED` bid referencing the takeoff is
        submitted, the takeoff transitions `DRAFT → LOCKED`, and from then on
        any attempt to add or remove lines against it is rejected with
        `ERR_TAKEOFF_LOCKED` (HTTP 409)."

        Design: Corner/state_machines/takeoff_locked_after_detailed_bid_submit
        """
        to, _client = self._setup_locked_takeoff(api)
        # Read current version (correct OCC), still rejected by the state gate
        now = get_success_data(api.get_takeoff(to["id"], EST))
        resp = api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": now["version"],
             "material_code": "PAINT_GAL", "quantity": 1, "source": "PURCHASE",
             "unit_cost_cents": 7500},
            EST,
        )
        validate_error(resp, ApiErrorId.ERR_TAKEOFF_LOCKED, 409)
        after = get_success_data(api.get_takeoff(to["id"], EST))
        assert after["status"] == "LOCKED"
        assert after["materials_subtotal_cents"] == 10000  # unchanged

    def test_delete_line_after_lock_fails_with_takeoff_locked(self, api):
        """PRD §3.2: "any attempt to add or remove lines against it is
        rejected with `ERR_TAKEOFF_LOCKED` (HTTP 409)."

        Design: Corner/state_machines/takeoff_locked_after_detailed_bid_submit
        """
        to, _client = self._setup_locked_takeoff(api)
        # Get the line id
        lines, _meta = validate_paginated(api.list_takeoff_lines(
            EST, params={"takeoff_id": to["id"]},
        ))
        line_id = lines[0]["id"]
        resp = api.delete_takeoff_line(line_id, EST)
        validate_error(resp, ApiErrorId.ERR_TAKEOFF_LOCKED, 409)


class TestTakeoffLineReverseReachability:
    def test_lines_reverse_reachable_by_stock_item(self, api):
        """PRD §3.2: "Takeoffs and their lines are discoverable through the
        filtered list endpoints — takeoffs by `design_package_id` and
        `status`, lines by `takeoff_id` and by `stock_item_id` (the latter
        giving reverse reachability from a stock item to every line consuming
        it)."

        Design: Corner/endpoints/takeoff_lines_reverse_reachable_by_stock_item
        """
        shop, client, pkg = setup_basic_scenario()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "B", "quantity_on_hand": 100,
             "replacement_cost_cents": 5000},
            ADMIN,
        ))
        to = get_success_data(api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10}, EST,
        ))
        line = get_success_data(api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "LUMBER_4X8", "quantity": 10, "source": "STOCK",
             "stock_item_id": si["id"]},
            EST,
        ))
        data, meta = validate_paginated(api.list_takeoff_lines(
            EST, params={"stock_item_id": si["id"]},
        ))
        assert meta["total_count"] == 1
        assert data[0]["id"] == line["id"]
        assert data[0]["stock_item_id"] == si["id"]
        assert data[0]["takeoff_id"] == to["id"]


class TestStockLineConservation:
    def test_create_then_delete_conserves_on_hand(self, api):
        """PRD §3.2: "Adding a `STOCK` line decrements the referenced item's
        `quantity_on_hand` by the line's `quantity` ... Removing a line from a
        draft takeoff compensates: a `STOCK` line's quantity is added back to
        the item's `quantity_on_hand`."

        Design: Difficulty/compensating_invariant/stock_line_create_delete_conserves_quantity
        """
        shop, client, pkg = setup_basic_scenario()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 100,
             "replacement_cost_cents": 3000},
            ADMIN,
        ))
        to = get_success_data(api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10}, EST,
        ))
        line = get_success_data(api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "LUMBER_4X8", "quantity": 30, "source": "STOCK",
             "stock_item_id": si["id"]},
            EST,
        ))
        mid = get_success_data(api.get_stock_item(si["id"], ADMIN))
        assert mid["quantity_on_hand"] == 70
        # Delete restores
        del_resp = api.delete_takeoff_line(line["id"], EST)
        assert del_resp.status_code == 204
        end = get_success_data(api.get_stock_item(si["id"], ADMIN))
        assert end["quantity_on_hand"] == 100

    def test_delete_recomputes_takeoff_subtotal(self, api):
        """PRD §3.2: "The takeoff's `materials_subtotal_cents` is the sum of
        `line_total_cents` over all its lines, recomputed on every line
        addition or removal."

        Design: Difficulty/compensating_invariant/stock_line_create_delete_conserves_quantity
        """
        shop, client, pkg = setup_basic_scenario()
        si = get_success_data(api.create_stock_item(
            {"shop_id": shop["id"], "material_code": "LUMBER_4X8",
             "condition_grade": "A", "quantity_on_hand": 100,
             "replacement_cost_cents": 3000},
            ADMIN,
        ))
        to = get_success_data(api.create_takeoff(
            {"design_package_id": pkg["id"], "labor_hours_est": 10}, EST,
        ))
        line = get_success_data(api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "LUMBER_4X8", "quantity": 30, "source": "STOCK",
             "stock_item_id": si["id"]},
            EST,
        ))
        api.delete_takeoff_line(line["id"], EST)
        takeoff_after = get_success_data(api.get_takeoff(to["id"], EST))
        assert takeoff_after["materials_subtotal_cents"] == 0


class TestStockConsumeBoundary:
    def test_consume_exactly_on_hand_to_zero_depletes(self, api):
        """PRD §3.2: "if the requested quantity exceeds the on-hand quantity
        the request is rejected with `ERR_STOCK_INSUFFICIENT` (HTTP 409),
        though consuming exactly down to zero is allowed. The item's `status`
        flips from `ACTIVE` to `DEPLETED` whenever a mutation leaves
        `quantity_on_hand` at zero."

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
        line = get_success_data(api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "PAINT_GAL", "quantity": 30, "source": "STOCK",
             "stock_item_id": si["id"]},
            EST,
        ))
        assert line["line_total_cents"] == 72000  # 30 * 2400 (A: 4000*6000bp)
        si_after = get_success_data(api.get_stock_item(si["id"], ADMIN))
        assert si_after["quantity_on_hand"] == 0
        assert si_after["status"] == "DEPLETED"
        shop_after = get_success_data(api.get_shop(shop["id"], ADMIN))
        assert shop_after["inventory_value_cents"] == 0

    def test_consume_one_over_on_hand_returns_insufficient(self, api):
        """PRD §3.2: "if the requested quantity exceeds the on-hand quantity
        the request is rejected with `ERR_STOCK_INSUFFICIENT` (HTTP 409)."

        Design: Corner/errors/stock_line_over_on_hand_returns_insufficient
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
        resp = api.create_takeoff_line(
            {"takeoff_id": to["id"], "expected_takeoff_version": to["version"],
             "material_code": "PAINT_GAL", "quantity": 31, "source": "STOCK",
             "stock_item_id": si["id"]},
            EST,
        )
        validate_error(resp, ApiErrorId.ERR_STOCK_INSUFFICIENT, 409)
        si_after = get_success_data(api.get_stock_item(si["id"], ADMIN))
        assert si_after["quantity_on_hand"] == 30
        to_after = get_success_data(api.get_takeoff(to["id"], EST))
        assert to_after["materials_subtotal_cents"] == 0


class TestPackageSupersession:
    def test_reupload_supersedes_prior_and_bumps_revision(self, api):
        """PRD §2.9: "When a client uploads a package for a pair that
        already has a `CURRENT` package, the prior package transitions to
        `SUPERSEDED` and the new upload becomes the sole `CURRENT` package,
        its `drawing_revision` set to one greater than the highest prior
        revision for that pair."

        Design: Corner/state_machines/package_reupload_supersedes_prior_and_bumps_revision
        """
        from test_helpers import setup_design_package
        _, client, pkg_1 = setup_basic_scenario()
        pkg_2 = setup_design_package(
            client["id"], show_title="Hamlet",
            load_in_at="2026-09-27T00:00:00Z", strike_at="2026-10-11T00:00:00Z",
        )
        # pkg_1 now SUPERSEDED with revision 1
        p1 = get_success_data(api.get_design_package(pkg_1["id"], EST))
        assert p1["status"] == "SUPERSEDED"
        assert p1["drawing_revision"] == 1
        # pkg_2 CURRENT with revision 2
        assert pkg_2["status"] == "CURRENT"
        assert pkg_2["drawing_revision"] == 2
        # Exactly one CURRENT per (client_id, show_title)
        data, meta = validate_paginated(api.list_design_packages(
            EST, params={"client_id": client["id"], "status": "CURRENT"},
        ))
        assert meta["total_count"] == 1
        assert data[0]["id"] == pkg_2["id"]
