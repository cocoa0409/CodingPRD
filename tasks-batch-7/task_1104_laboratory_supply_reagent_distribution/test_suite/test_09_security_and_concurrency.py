"""Security and concurrency: context headers, role authorization, customer
ownership, existence-before-state ordering, and optimistic version control."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    get_lot,
    get_order,
    make_customer,
    make_customer_headers,
    make_lot,
    make_order,
    make_product,
    make_recall,
    make_warehouse,
    make_zone,
    order_line,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]
CATALOG = TEST_USERS["catalog_manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]
ACCOUNTS = TEST_USERS["account_manager_headers"]


class TestContextAndRoles:
    def test_request_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request in which either header is missing, or in which `X-User-Role` is not one of these six values, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_headers_rejected
        """
        resp = api.list_warehouses(headers={"X-User-ID": "test-no-role"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400

    def test_customer_cannot_create_warehouse_returns_forbidden(self, api):
        """PRD §2.1: "Once the context is accepted, each operation is restricted to a designated role list; an authenticated caller whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "In brief: `OpsAdmin` operates the distribution network itself (warehouses, storage zones, and the logical clock);"

        Design: Corner/roles/customer_cannot_create_warehouse_returns_forbidden
        """
        customer = make_customer(api, name="Lab Mu")
        resp = api.create_warehouse(
            {"name": "WH-X", "region_code": "US-NE", "hazmat_certified": False},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_quality_manager_cannot_receive_lots(self, api):
        """PRD §2.1: "Once the context is accepted, each operation is restricted to a designated role list; an authenticated caller whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "`InventoryClerk` works the warehouse floor (lot receipt and adjustment, shipments, kit assembly); `QualityManager` owns quarantine, recalls, and excursion disposition;"

        Design: Corner/roles/quality_manager_cannot_receive_lots
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=100)
        product = make_product(api, sku="CH-105", name="Buffer Salt", unit_price_cents=105)
        resp = api.create_lot(
            {
                "product_id": product["id"],
                "warehouse_id": warehouse["id"],
                "storage_zone_id": zone["id"],
                "quantity_received": 5,
                "manufacture_date": "2026-01-15",
            },
            QUALITY,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_account_manager_cannot_issue_recall(self, api):
        """PRD §2.1: "Once the context is accepted, each operation is restricted to a designated role list; an authenticated caller whose role is not on that list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §3.7: "When quality fails at scale, a `QualityManager` authors a recall notice naming the `product_id`, a `scope_type` of `LOT_RANGE` or `PRODUCT_ALL`, the `severity_class` of `CLASS_I`, `CLASS_II`, or `CLASS_III`, and a free-text `reason`."

        Design: Corner/roles/account_manager_cannot_issue_recall
        """
        product = make_product(api, sku="CH-105", name="Buffer Salt", unit_price_cents=105)
        recall = make_recall(api, product_id=product["id"], scope_type="PRODUCT_ALL")
        resp = api.issue_recall(recall["id"], ACCOUNTS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        after = validate_success(api.get_recall(recall["id"], QUALITY), 200)
        assert after["status"] == "DRAFT", "the rejected issuance leaves the recall DRAFT"


class TestCustomerOwnership:
    def test_customer_cannot_submit_another_customers_order(self, api):
        """PRD §2.1: "This ownership rule guards every customer-scoped mutation — submitting, reallocating, or cancelling an order, releasing a reservation, creating or pausing or resuming or cancelling a standing order, and recording consignment consumption — and a mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_VIOLATION` (HTTP 403)."
        PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a `CustomerAccount` compare the resource's `customer_id` field to `X-User-ID`."

        Design: Corner/roles/customer_cannot_submit_another_customers_order
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(api, sku="CH-1000", unit_price_cents=1000)
        cust_a = make_customer(api, name="Lab A")
        cust_b = make_customer(api, name="Lab B")
        make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=10)
        order = make_order(
            api, cust_a["id"], warehouse["id"], [order_line(product["id"], 1, "ANY")]
        )

        resp = api.submit_order(order["id"], make_customer_headers(cust_b["id"]))
        validate_error(resp, ApiErrorId.ERR_RESOURCE_OWNERSHIP_VIOLATION)
        assert resp.status_code == 403
        assert get_order(api, order["id"])["status"] == "DRAFT", (
            "the ownership violation fires before any state change"
        )


class TestExistenceOrdering:
    def test_existence_checked_before_state_ordering(self, api):
        """PRD §2.6: "All requests are evaluated against a fixed validation priority chain, and a higher-priority failure always masks lower-priority ones — the caller sees exactly one error, from the earliest failing stage:"
        PRD §2.6: "3. **Customer ownership** — for `Customer`-role mutations, `X-User-ID` must equal the target's `customer_id`, else `ERR_RESOURCE_OWNERSHIP_VIOLATION`; when the target does not exist this stage is skipped and stage 4 reports the 404."
        PRD §2.6: "4. **Existence** — path ids left to right, then body-referenced ids in declared input order, each yielding its per-resource 404."

        Design: Corner/validations/existence_checked_before_state_ordering
        """
        customer = make_customer(api, name="Lab Mu")
        resp = api.cancel_order(NON_EXISTENT_UUID, make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)
        assert resp.status_code == 404


class TestLotAdjustmentOcc:
    def test_occ_lot_adjustment_stale_version_rejected(self, api):
        """PRD §2.7: "`POST /lab/lots/{lotId}/adjustments` requires `expected_lot_version`. When it no longer matches the lot's current `version` — because an earlier adjustment, cascade, or reservation flow already advanced it — the adjustment is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), so the client re-reads before correcting stock."
        PRD §3.2: "The delta is applied to `quantity_on_hand` and accumulated into `adjustment_total`; an adjustment that would drive `quantity_on_hand` below zero is rejected with `ERR_ADJUSTMENT_BELOW_ZERO`."

        Design: Corner/cross_cutting_layers/occ_lot_adjustment_stale_version_rejected
        """
        warehouse = make_warehouse(api)
        zone = make_zone(api, warehouse["id"], zone_class="AMBIENT", capacity_units=500)
        product = make_product(api, sku="CH-105", name="Buffer Salt", unit_price_cents=105)
        lot = make_lot(api, product["id"], warehouse["id"], zone["id"], quantity_received=20)
        observed_version = lot["version"]

        first = api.adjust_lot(
            lot["id"],
            {"delta": 5, "reason": "cycle count surplus",
             "expected_lot_version": observed_version},
            CLERK,
        )
        adjusted = validate_success(first, 201)
        assert adjusted["quantity_on_hand"] == 25
        assert adjusted["version"] == observed_version + 1

        second = api.adjust_lot(
            lot["id"],
            {"delta": 5, "reason": "cycle count surplus again",
             "expected_lot_version": observed_version},
            CLERK,
        )
        validate_error(second, ApiErrorId.ERR_STALE_LOT_VERSION)
        assert second.status_code == 412

        after = get_lot(api, lot["id"])
        assert after["quantity_on_hand"] == 25, "the stale adjustment applies nothing"
        assert after["adjustment_total"] == 5
