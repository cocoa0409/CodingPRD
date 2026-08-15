"""Cross-cutting platform behavior: auth gates, role denials, Grower ownership
scoping, per-resource 404s, the error envelope, and list pagination."""
from test_helpers import (
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    close_shift,
    create_grade_schedule_payload,
    create_grower,
    create_grower_payload,
    create_module,
    create_seed_sale_payload,
    create_settlement_payload,
    create_shift,
    get_grower,
    get_module,
    gin_module,
    list_module_bales,
    list_shift_seed_sales,
    make_grower_headers,
    queue_module,
    reconcile_shift,
    start_ginning,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["gin_operator_headers"]
CLERK = TEST_USERS["classing_clerk_headers"]
WM = TEST_USERS["warehouse_manager_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestAuthGate:
    def test_missing_auth_header_returns_401(self, api):
        """PRD: "A request missing either header, or carrying an empty value
        for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT`
        (HTTP 401)."
        PRD: "Authentication comes first — missing or empty `X-User-ID` /
        `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT` before
        anything else is examined."

        Design: Corner/validations/missing_auth_header_returns_401
        """
        resp = api.create_grower(
            create_grower_payload(membership_number="MB-C40",
                                  legal_name="No Auth"), NO_AUTH_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)


class TestRoleDenials:
    def test_ginoperator_cannot_create_grade_schedule(self, api):
        """PRD: "A request whose role is not permitted on the endpoint, or
        whose `Grower`-role caller touches a resource outside their own grower
        chain, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: "POST | `/gin-ops/grade-schedules` | Create a grade
        schedule window; same-grade half-open windows must not overlap |
        CoopAdmin"

        Design: Corner/rbac/rbac_ginoperator_cannot_create_grade_schedule
        """
        resp = api.create_grade_schedule(
            create_grade_schedule_payload(
                grade_code="41-4", premium_discount_points=-110,
                loan_rate_points=5200, effective_from="2026-01-01T00:00:00Z",
                effective_to="2026-07-01T00:00:00Z"), OPERATOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_classingclerk_cannot_complete_ginning(self, api):
        """PRD: "A request whose role is not permitted on the endpoint, or
        whose `Grower`-role caller touches a resource outside their own grower
        chain, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: "POST | `/gin-ops/modules/{id}/complete-ginning` |
        Record produced bales and finish ginning; posts the tiered ginning
        charge | GinOperator"

        Design: Corner/rbac/rbac_classingclerk_cannot_complete_ginning
        """
        grower = create_grower("MB-C71", "Role Farm")
        shift = create_shift("2026", "STAND-RB")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-RB")
        queue_module(module["id"], shift["id"])
        start_ginning(module["id"])

        resp = api.complete_ginning(
            module["id"], {"bales": [{"bale_tag": "B-RB1", "net_weight_lbs": 500}]},
            CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        assert get_module(module["id"])["status"] == "GINNING"
        assert list_module_bales(module["id"]) == []

    def test_warehousemanager_cannot_create_seed_sale(self, api):
        """PRD: "A request whose role is not permitted on the endpoint, or
        whose `Grower`-role caller touches a resource outside their own grower
        chain, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: "POST | `/gin-ops/seed-sales` | Sell a reconciled
        shift's pooled seed; allocates proceeds per grower | CoopAccountant"

        Design: Corner/rbac/rbac_warehousemanager_cannot_create_seed_sale
        """
        grower = create_grower("MB-C74", "Sale Role Farm")
        shift = create_shift("2026", "STAND-SR")
        module = create_module(grower["id"], ticket_number="T-1", module_tag="MT-SR")
        gin_module(module["id"], shift["id"], [("B-SR1", 1000)])
        close_shift(shift["id"], 1000, 8000, 1000)
        reconcile_shift(shift["id"])

        resp = api.create_seed_sale(
            create_seed_sale_payload(shift["id"], buyer_name="Wrong Role Mill",
                                     price_cents_per_lb=20), WM)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert list_shift_seed_sales(shift["id"]) == []


class TestGrowerOwnership:
    def test_grower_reads_self_but_not_other_grower(self, api):
        """PRD: "When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the
        acting `Grower`; ownership checks on any resource that references a
        `Grower` compare the resource's grower-chain foreign key to
        `X-User-ID`, and a mismatch yields `ERR_FORBIDDEN`."

        Design: Corner/rbac/rbac_grower_cannot_read_other_grower
        """
        g1 = create_grower("MB-C72A", "Self Farm")
        g2 = create_grower("MB-C72B", "Other Farm")

        own = validate_success(api.get_grower(g1["id"],
                                              make_grower_headers(g1["id"])))
        assert own["id"] == g1["id"]

        resp = api.get_grower(g2["id"], make_grower_headers(g1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_grower_cannot_create_settlement(self, api):
        """PRD: "A request whose role is not permitted on the endpoint, or
        whose `Grower`-role caller touches a resource outside their own grower
        chain, is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD endpoint table: "POST | `/gin-ops/growers/{growerId}/settlements` |
        Create a superseding settlement for grower+season; OCC on
        Grower.version | CoopAccountant"

        Design: Corner/rbac/rbac_grower_cannot_create_settlement
        """
        g1 = create_grower("MB-C73", "Self Settle Farm")
        resp = api.create_settlement(
            g1["id"], create_settlement_payload("2026", g1["version"]),
            make_grower_headers(g1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        data, meta = validate_paginated(api.list_grower_settlements(
            g1["id"], make_grower_headers(g1["id"])))
        assert meta["total_count"] == 0


class TestNotFoundMatrix:
    def test_per_resource_404_error_ids(self, api):
        """PRD: "Existence of every path resource id (validated left-to-right
        along the URL) and every body foreign-key reference is checked next,
        yielding the resource-specific not-found error —
        `ERR_GROWER_NOT_FOUND`, `ERR_MODULE_NOT_FOUND`, `ERR_BALE_NOT_FOUND`,
        `ERR_GIN_SHIFT_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`,
        `ERR_WAREHOUSE_RECEIPT_NOT_FOUND`, `ERR_LOAN_PLEDGE_NOT_FOUND`,
        `ERR_SETTLEMENT_NOT_FOUND`, `ERR_SHIPPING_ORDER_NOT_FOUND`,
        `ERR_GRADE_SCHEDULE_NOT_FOUND`, or `ERR_LEDGER_ENTRY_NOT_FOUND`, each
        at HTTP 404."

        Design: Corner/entities/resource_not_found_matrix_returns_per_resource_404
        """
        cases = [
            (api.get_grower(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_GROWER_NOT_FOUND),
            (api.get_module(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_MODULE_NOT_FOUND),
            (api.get_bale(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_BALE_NOT_FOUND),
            (api.get_gin_shift(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_GIN_SHIFT_NOT_FOUND),
            (api.get_warehouse(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_WAREHOUSE_NOT_FOUND),
            (api.get_warehouse_receipt(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_WAREHOUSE_RECEIPT_NOT_FOUND),
            (api.get_loan_pledge(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_LOAN_PLEDGE_NOT_FOUND),
            (api.get_settlement(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_SETTLEMENT_NOT_FOUND),
            (api.get_shipping_order(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_SHIPPING_ORDER_NOT_FOUND),
            (api.get_grade_schedule(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_GRADE_SCHEDULE_NOT_FOUND),
            (api.get_ledger_entry(NON_EXISTENT_UUID, ADMIN),
             ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
        ]
        for resp, error_id in cases:
            validate_error(resp, error_id)


class TestErrorEnvelope:
    def test_error_envelope_shape_on_404(self, api):
        """PRD: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/endpoints/error_envelope_shape_on_404
        """
        resp = api.get_module(NON_EXISTENT_UUID, ADMIN)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_MODULE_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]


class TestPagination:
    def test_modules_list_pagination_defaults(self, api):
        """PRD: "List endpoints accept two query parameters: `limit` (default
        10, minimum 1, maximum 100) and `offset` (default 0). Results are
        returned sorted by `created_at` ascending. The `meta` block of a list
        response carries four pagination fields: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/modules_list_pagination_defaults
        """
        grower = create_grower("MB-C60", "Page Farm")
        for i in range(1, 12):
            create_module(grower["id"], ticket_number=f"T-{i:02d}",
                          module_tag=f"MT-P{i:02d}")

        page1, meta1 = validate_paginated(
            api.list_modules(OPERATOR, params={"grower_id": grower["id"]}))
        assert len(page1) == 10, "default limit 10 applied"
        assert meta1["total_count"] == 11
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert all(row["grower_id"] == grower["id"] for row in page1)

        page2, meta2 = validate_paginated(api.list_modules(
            OPERATOR, params={"grower_id": grower["id"], "offset": 10}))
        assert len(page2) == 1
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False
