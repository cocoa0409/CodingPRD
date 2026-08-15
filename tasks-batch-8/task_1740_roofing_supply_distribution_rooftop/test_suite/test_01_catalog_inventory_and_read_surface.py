"""Branch/product/lot creation defaults, read surface, auth and RBAC basics."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_branch,
    assert_inventory_lot,
    assert_product,
    convert_to_order,
    create_quoted_takeoff,
    make_account,
    make_branch,
    make_contractor_headers,
    make_job,
    make_lot,
    make_product,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)

ADMIN = TEST_USERS["platform_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
CREDIT = TEST_USERS["credit_analyst_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]


class TestCatalogDefaults:
    def test_branch_creation_applies_status_and_surge_mode_defaults(self, api):
        """PRD §3.1: "A new branch starts with `status` set to `ACTIVE` — the
        only branch status in this version of the system, branch lifecycle
        being out of scope — and with `surge_mode` set to `NORMAL`, a flag
        that flips to `SURGE` only while a storm event is active (§3.6)."

        Design: Corner/entities/branch_creation_applies_defaults
        """
        branch = validate_success(api.create_branch(
            {"branch_code": "BR-E1", "name": "Ent",
             "rooftop_delivery_capacity_per_day": 4, "conveyor_fleet_size": 2,
             "crane_available": True}, ADMIN), expected_status=201)
        assert_branch(branch)
        assert branch["status"] == "ACTIVE"
        assert branch["surge_mode"] == "NORMAL"

    def test_product_requires_certified_installer_defaults_false(self, api):
        """PRD §3.1: "Products whose warranty registration demands a
        manufacturer-certified installer are flagged with
        `requires_certified_installer`, which defaults to false when omitted."
        PRD §3.1: "Products also carry a `status` of `ACTIVE`, again the only
        value in this version."

        Design: Corner/entities/product_requires_certified_installer_defaults_false
        """
        product = validate_success(api.create_product(
            {"sku": "SH-E2", "manufacturer_name": "Acme", "color_code": "BLK",
             "bundles_per_square": 3.0, "base_price_per_bundle_cents": 3000},
            ADMIN), expected_status=201)
        assert_product(product)
        assert product["requires_certified_installer"] is False
        assert product["status"] == "ACTIVE"

    def test_inventory_lot_available_bundles_computed_from_counters(self, api):
        """PRD §2.7: "The read-only `available_bundles` figure is the on-hand
        count minus the reserved count, floored at zero so a lot never reports
        negative availability."
        PRD §3.1: "receiving either creates the lot or tops up an existing
        one, and a fresh lot always starts with `reserved_bundles` at zero."

        Design: Corner/entities/inventory_lot_available_bundles_computed
        """
        branch = make_branch("BR-E3", name="Ent3")
        product = make_product("SH-E3", price=3000, color_code="GRY")
        lot = validate_success(api.receive_inventory_lot(
            branch["id"],
            {"product_id": product["id"], "lot_code": "LOT-E3",
             "on_hand_bundles": 120}, WAREHOUSE), expected_status=201)
        assert_inventory_lot(lot)
        assert lot["reserved_bundles"] == 0
        assert lot["available_bundles"] == 120


class TestReadSurface:
    def test_get_nonexistent_order_returns_404(self, api):
        """PRD §3.4: "an unknown order id is `ERR_ORDER_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_order_returns_404
        """
        resp = api.get_order(NON_EXISTENT_UUID, SALES)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_list_orders_pagination_envelope(self, api):
        """PRD §2.3: "Paginated list responses carry the fields `limit`,
        `offset`, `total_count`, and `has_more` in the `meta` object of the
        response envelope."
        PRD §2.3: "The `limit` parameter caps the number of items returned:
        it defaults to 10, accepts a minimum of 1, and is clamped at a maximum
        of 100."
        PRD §3.4: "orders themselves list with optional filters on `status`,
        `job_account_id`, `takeoff_id`, `branch_id`, and
        `storm_surge_event_id`, and an unknown order id is
        `ERR_ORDER_NOT_FOUND`."

        Design: Corner/endpoints/list_orders_pagination_envelope
        """
        branch = make_branch("BR-EP1", name="EP1")
        product = make_product("SH-EP1", price=2000)
        account = make_account(name="EP Co")
        job = make_job(account["id"])
        takeoff = create_quoted_takeoff(job["id"], product["id"],
                                        roof_squares=5.0)
        convert_to_order(takeoff["id"], branch["id"], account["id"])

        resp = api.list_orders(SALES, params={"job_account_id": job["id"]})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"expected exactly 1 order, got {len(data)}"
        assert meta["limit"] == 10, "default limit must be 10"
        assert meta["offset"] == 0
        assert meta["total_count"] == 1
        assert meta["has_more"] is False

    def test_order_lines_reverse_reachable_from_order(self, api):
        """PRD §3.3: "Conversion creates an Order in `QUOTED` status
        containing exactly one OrderLine: the line's `product_id` is the
        takeoff's product and its `quantity_bundles` is the shingle-bundles
        component of the estimate."
        PRD §3.4: "Order lines can be browsed per order or across orders with
        optional filters by `product_id`, `inventory_lot_id`, or `order_id`;
        orders themselves list with optional filters on `status`,
        `job_account_id`, `takeoff_id`, `branch_id`, and
        `storm_surge_event_id`, and an unknown order id is
        `ERR_ORDER_NOT_FOUND`."

        Design: Corner/endpoints/order_lines_reverse_reachable_from_order
        """
        branch = make_branch("BR-EP2", name="EP2")
        product = make_product("SH-EP2", price=2000)
        account = make_account(name="EP2 Co")
        job = make_job(account["id"])
        takeoff = create_quoted_takeoff(job["id"], product["id"],
                                        roof_squares=5.0)
        order = convert_to_order(takeoff["id"], branch["id"], account["id"])

        data, _meta = validate_paginated(api.list_order_lines(order["id"], SALES))
        assert len(data) == 1, f"expected exactly 1 order line, got {len(data)}"
        # 5.0 squares * 3.0 bundles/square = 15 shingle bundles, waste 0.
        assert data[0]["quantity_bundles"] == 15
        assert data[0]["product_id"] == product["id"]

    def test_filtered_list_inventory_lots_by_product(self, api):
        """PRD §3.1: "Lot ledgers can be browsed per branch or across
        branches, with optional filters by `product_id` and, on the
        cross-branch view, `branch_id`."

        Design: Corner/endpoints/filtered_list_inventory_lots_by_product
        """
        branch = make_branch("BR-EP3", name="EP3")
        product_a = make_product("SH-EP3A", price=2000, color_code="BLK")
        product_b = make_product("SH-EP3B", price=3000, bps=4.0,
                                 color_code="WHT")
        make_lot(branch["id"], product_a["id"], on_hand=50, lot_code="LOT-A")
        make_lot(branch["id"], product_b["id"], on_hand=70, lot_code="LOT-B")

        data, _meta = validate_paginated(api.list_branch_inventory_lots(
            branch["id"], WAREHOUSE, params={"product_id": product_a["id"]}))
        assert len(data) == 1, f"expected exactly 1 lot, got {len(data)}"
        assert data[0]["lot_code"] == "LOT-A"
        assert data[0]["product_id"] == product_a["id"]


class TestAuthAndRbac:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing or empty is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP
        400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        # X-User-Role omitted entirely.
        resp = api.list_branches({"X-User-ID": "test-no-role-1"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_nonexistent_branch_in_path_404(self, api):
        """PRD §2.9: "The same discipline applies everywhere: a missing branch
        surfaces `ERR_BRANCH_NOT_FOUND`, a missing product
        `ERR_PRODUCT_NOT_FOUND`, a missing lot `ERR_LOT_NOT_FOUND`, and so on
        for every resource type in the catalogue (§5)."

        Design: Corner/validations/nonexistent_branch_in_path_404
        """
        product = make_product("SH-VL2", price=2000)
        resp = api.receive_inventory_lot(
            NON_EXISTENT_UUID,
            {"product_id": product["id"], "lot_code": "LOT-X",
             "on_hand_bundles": 10}, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_BRANCH_NOT_FOUND)

    def test_contractor_cannot_create_branch(self, api):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (§4); a caller
        whose role is not admitted, or a `Contractor` attempting to act on
        another contractor's resources, is rejected with `ERR_FORBIDDEN` (HTTP
        403)."
        PRD §4: POST /roofing/branches — "Create a branch | PlatformAdmin".

        Design: Corner/rbac/contractor_cannot_create_branch
        """
        account = make_account(name="RB1 Co")
        resp = api.create_branch(
            {"branch_code": "BR-RB1", "name": "RB1",
             "rooftop_delivery_capacity_per_day": 4, "conveyor_fleet_size": 2,
             "crane_available": True},
            make_contractor_headers(account["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
