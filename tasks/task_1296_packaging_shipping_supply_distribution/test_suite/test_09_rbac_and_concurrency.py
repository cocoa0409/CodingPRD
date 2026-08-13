"""Role-based access control denials, authentication failure, and optimistic
concurrency on the catalog update path."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    create_draft_order,
    create_inventory,
    create_product_payload,
    create_stock_product,
    create_warehouse,
    make_approver_headers,
    make_buyer_headers,
    request_return,
    set_clock,
    setup_shipped_stock_order,
    setup_warehouse_and_account,
    ship_order,
    submit_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
OPS = TEST_USERS["warehouse_ops_headers"]
SERVICE = TEST_USERS["customer_service_headers"]


class TestBuyerDeniedOutsideLane:
    def test_buyer_cannot_create_products_or_receive_inventory(self, api):
        """PRD section 2.1: "A request whose role is not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: "| POST | `/packaging-distribution/products` | Create a catalog product | CatalogManager |"
        PRD section 4: "| POST | `/packaging-distribution/inventory/{id}/receive` | Receive stock into a row | WarehouseOps |"

        Design: Corner/rbac/rbac_buyer_cannot_manage_catalog_or_inventory
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="Y-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        inv = create_inventory(prod["id"], wh["id"], 10)
        buyer = make_buyer_headers(acct["id"])

        create_as_buyer = api.create_product(
            create_product_payload(sku="Y-2", base_price_cents=100, pallet_qty=10,
                                   weight_lbs_per_unit=1), buyer)
        validate_error(create_as_buyer, ApiErrorId.ERR_UNAUTHORIZED)

        receive_as_buyer = api.receive_inventory(inv["id"], {"qty": 5}, buyer)
        validate_error(receive_as_buyer, ApiErrorId.ERR_UNAUTHORIZED)


class TestApprovalChainLanes:
    def test_warehouseops_cannot_approve_return_and_approver_cannot_submit(self, api):
        """PRD section 2.1: "A request whose role is not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 4: "| POST | `/packaging-distribution/returns/{id}/approve` | Approve a requested return, computing fee and refund | CustomerService |"
        PRD section 4: "| POST | `/packaging-distribution/orders/{id}/submit` | Submit a draft order: pricing, allocation, provisional freight, promise date | Buyer |"

        Design: Corner/rbac/rbac_warehouseops_cannot_approve_returns_approver_cannot_submit
        """
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="Z-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        create_inventory(prod["id"], wh["id"], 100)
        set_clock("2026-08-03T10:00:00Z")

        o1 = create_draft_order(acct["id"], ship_zone=5)
        l1 = add_line(o1["id"], acct["id"], prod["id"], 1)
        submit_order(o1["id"], acct["id"])
        ship_order(o1["id"])
        ret = request_return(o1["id"], acct["id"],
                             [{"order_line_id": l1["id"], "qty": 1}], reason_code="DAMAGED")

        approve_as_ops = api.approve_return(ret["id"], OPS)
        validate_error(approve_as_ops, ApiErrorId.ERR_UNAUTHORIZED)

        o2 = create_draft_order(acct["id"], ship_zone=5)
        add_line(o2["id"], acct["id"], prod["id"], 1)
        submit_as_approver = api.submit_order(o2["id"], make_approver_headers(acct["id"]))
        validate_error(submit_as_approver, ApiErrorId.ERR_UNAUTHORIZED)


class TestUnauthenticated:
    def test_missing_headers_rejected_as_unauthenticated(self, api):
        """PRD section 2.1: "Every request must carry two HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, naming
        their operational capacity."
        PRD section 2.1: "A request with missing headers, or with a role that
        is not one of these declared names, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/rbac_missing_auth_headers_unauthenticated
        """
        resp = api.list_products(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestProductUpdateOcc:
    def test_stale_product_update_rejected_and_losing_write_leaves_no_trace(self, api):
        """PRD section 2.7: "The full catalog update of a product requires the
        client to send `expected_product_version` carrying the version of the
        product record it last observed; if the product's current `version` has
        advanced since that read — for example because another catalog change
        altered pricing or pallet configuration — the update is rejected with
        `ERR_STALE_VERSION` (HTTP 412) rather than silently discarding the
        newer state."
        PRD section 3.2: "A successful update recomputes `ship_method` if the
        oversize flag changed and increments the product's `version`."

        Design: Corner/cross_cutting_layers/occ_product_update_stale_version_rejected
        """
        prod = create_stock_product(sku="AB-1", base_price_cents=1000, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        observed_v = prod["version"]

        first = validate_success(api.update_product(
            prod["id"], {"expected_product_version": observed_v, "base_price_cents": 1100},
            CATALOG))
        assert first["version"] == observed_v + 1

        stale = api.update_product(
            prod["id"], {"expected_product_version": observed_v, "base_price_cents": 1200},
            CATALOG)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        end = validate_success(api.get_product(prod["id"], CATALOG))
        assert end["base_price_cents"] == 1100, "the losing write must leave no trace"
        assert end["version"] == first["version"]
