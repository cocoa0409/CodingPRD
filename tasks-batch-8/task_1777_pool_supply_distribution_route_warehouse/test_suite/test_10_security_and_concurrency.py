"""Security and concurrency: role-permission denials, entity-backed ownership,
the mandatory user-context headers, and branch-version OCC on confirmation."""
from test_helpers import (
    ApiErrorId,
    MGR,
    branch_version,
    create_confirmed_order,
    make_account,
    make_account_headers,
    make_branch,
    make_lot,
    make_order,
    make_product,
    order_line,
    setup_branch_account_product_lot,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

COUNTER = TEST_USERS["counter_rep_headers"]
WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


class TestRoleDenials:
    def test_counterrep_cannot_invoice(self, api):
        """PRD §2.1: "Access to each operation is further restricted by role; acting outside one's role draws `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.6: "The payment dimension runs in parallel to fulfillment, independently: from `UNINVOICED`, invoicing by a `BranchManager` requires fulfillment `CONFIRMED` (`ERR_ORDER_NOT_CONFIRMED`) and payment still `UNINVOICED` (`ERR_ORDER_ALREADY_INVOICED`, HTTP 409); it freezes `invoiced_cents`, adds that amount into the account's `ytd_volume_cents`, recomputes the account's tier — which may ratchet upward but never downward — and moves payment to `INVOICED`."

        Design: Corner/rbac/counterrep_cannot_invoice
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-20"},
            product_over={"sku": "GLOVE-L", "product_family": "PARTS", "base_price_cents": 800},
            lot_over={"qty_on_hand": 5},
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 1)],
        )
        resp = api.invoice_order(order["id"], COUNTER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        order_after = validate_success(api.get_order(order["id"], MGR))
        assert order_after["payment_status"] == "UNINVOICED"

    def test_warehouselead_cannot_create_products(self, api):
        """PRD §2.1: "Access to each operation is further restricted by role; acting outside one's role draws `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.1: "`BranchManager` — the branch general manager, holding the full administrative surface: the logical clock, branch and catalog creation, account administration, seasonal program and commitment management, invoicing, backorder cancellation, service-center registration, warranty adjudication, and RMA approval."

        Design: Corner/rbac/warehouselead_cannot_create_products
        """
        resp = api.create_product(
            {"sku": "X", "product_family": "PARTS", "base_price_cents": 100},
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_account_cannot_act_on_other_accounts_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `Account`, `X-User-ID` is the `id` of the acting `Account` entity; ownership checks on any resource that references an account compare the resource's `account_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
        PRD §2.9: "First come authentication checks: header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role permission for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`), then entity-backed ownership — an `Account` principal may only act on resources whose `account_id` equals its `X-User-ID` (`ERR_NOT_RESOURCE_OWNER`), a rule enforced on order confirm, order cancel, order pay, claim supply-info, and RMA creation."

        Design: Corner/rbac/account_cannot_act_on_other_accounts_order
        """
        branch = make_branch(api, hazmat_storage_certified=False)
        a_a = make_account(api, account_number="DLR-21A")
        a_b = make_account(api, account_number="DLR-21B")
        product = make_product(api, sku="ROPE-50", product_family="PARTS", base_price_cents=900)
        make_lot(api, branch_id=branch["id"], product_id=product["id"], qty_on_hand=5)
        order = make_order(
            api, branch_id=branch["id"], account_id=a_a["id"],
            lines=[order_line(product["id"], 1)],
        )
        # Account B attempts to confirm account A's order.
        resp = api.confirm_order(
            order["id"],
            {"expected_branch_version": branch_version(branch["id"], api)},
            make_account_headers(a_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
        order_after = validate_success(api.get_order(order["id"], MGR))
        assert order_after["fulfillment_status"] == "DRAFT"

    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "Every request carries two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/missing_auth_headers_rejected
        """
        resp = api.list_branches(
            {"X-User-ID": "anonymous-1", "Content-Type": "application/json"}
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestBranchVersionOcc:
    def test_occ_stale_branch_version_on_confirm(self, api):
        """PRD §2.8: "**Order confirmation** requires a non-optional `expected_branch_version` carrying the client's last observed `version` of the fulfilling branch. If the branch's version has advanced since that observation, the request is rejected with `ERR_STALE_BRANCH_VERSION` (HTTP 412)."
        PRD §3.4: "Finally the branch's `version` increments by one, because confirmation has mutated branch-scoped derived state — the posture cascade and possibly the pool figure."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_branch_version_on_confirm
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-22"},
            product_over={"sku": "WHEEL-W", "product_family": "PARTS", "base_price_cents": 1100},
            lot_over={"qty_on_hand": 10},
        )
        stale = branch_version(branch["id"], api)
        o1 = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 1)],
        )
        o2 = make_order(
            api, branch_id=branch["id"], account_id=account["id"],
            requested_pickup_slot="2026-08-01T14:00:00Z",
            lines=[order_line(product["id"], 1)],
        )
        # The first confirm advances Branch.version...
        validate_success(
            api.confirm_order(o1["id"], {"expected_branch_version": stale}, COUNTER), 200
        )
        # ...so the second confirm against the stale snapshot is rejected.
        resp = api.confirm_order(o2["id"], {"expected_branch_version": stale}, COUNTER)
        validate_error(resp, ApiErrorId.ERR_STALE_BRANCH_VERSION)
        order_after = validate_success(api.get_order(o2["id"], MGR))
        assert order_after["fulfillment_status"] == "DRAFT", (
            f"the losing writer stays DRAFT and retries with a fresh version: {order_after}"
        )
