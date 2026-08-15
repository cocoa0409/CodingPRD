"""RBAC denial paths (PRD §2.1, §4) and the not-found catalog (PRD §2.8)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_active_salon,
    create_draft_order,
    make_brand,
    make_consultant,
    make_product,
    make_salon,
    make_salon_buyer_headers,
    submit_license,
    submit_order,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]


class TestRoleExclusiveDenials:
    def test_salon_buyer_cannot_approve_order(self, api):
        """PRD §2.1: "A request whose role is not listed for the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: "| POST | /api/orders/{id}/approve | Approve a SUBMITTED order
        | DistributionAdmin |"

        Design: Corner/rbac/salon_buyer_cannot_approve_order
        """
        salon, _ = create_active_salon()
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=3000)
        order = create_draft_order(
            salon["id"], [{"product_id": product["id"], "quantity": 1}])
        submit_order(order["id"], salon["id"])

        resp = api.approve_order(
            order["id"], make_salon_buyer_headers(salon["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        refreshed = api.get_order(order["id"], ADMIN).json()["data"]
        assert refreshed["fulfillment_status"] == "SUBMITTED"

    def test_warehouse_cannot_verify_license(self, api):
        """PRD §2.1: "A request whose role is not listed for the target
        endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: "| POST | /api/licenses/{id}/verify | Verify a SUBMITTED
        license; may activate the salon | ComplianceOfficer |"

        Design: Corner/rbac/warehouse_cannot_verify_license
        """
        consultant = make_consultant()
        salon = make_salon(legal_name="Salon 42", consultant=consultant)
        license_row = submit_license(salon["id"], license_type="BARBER")

        resp = api.verify_license(license_row["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        refreshed = api.get_license(license_row["id"], ADMIN).json()["data"]
        assert refreshed["status"] == "SUBMITTED"


class TestOwnershipScope:
    def test_salon_buyer_cannot_read_other_salon_order(self, api):
        """PRD §2.1: "When `X-User-Role` is `SalonBuyer`, `X-User-ID` is the
        `id` of the acting `SalonAccount`; the buyer acts only on its own
        salon's resources — any target whose `salon_account_id` does not equal
        `X-User-ID` is out of scope."
        PRD §2.1: "Ownership violations by entity-backed callers are rejected
        with `ERR_FORBIDDEN_RESOURCE` (HTTP 403)."

        Design: Corner/rbac/salon_buyer_cannot_read_other_salon_order
        """
        salon_a, _ = create_active_salon(legal_name="Salon 43A")
        salon_b, _ = create_active_salon(legal_name="Salon 43B")
        brand = make_brand()
        product = make_product(brand["id"], base_price_cents=3000)
        order_b = create_draft_order(
            salon_b["id"], [{"product_id": product["id"], "quantity": 1}])

        resp = api.get_order(
            order_b["id"], make_salon_buyer_headers(salon_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE)


class TestAuthenticationContext:
    def test_request_without_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request missing either header, presenting a role
        outside the declared set, or — for entity-backed roles — presenting an
        `X-User-ID` that does not resolve to an existing entity of the backing
        type, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/rbac/request_without_auth_headers_returns_400
        """
        resp = api.list_brands(headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestNotFoundCatalog:
    """PRD §2.8: "**Existence** — path- and body-referenced resource ids exist,
    validated left-to-right along the path, yielding the resource-specific
    `ERR_<RESOURCE>_NOT_FOUND` (404)."
    """

    def test_salon_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/entities/salon_get_nonexistent_returns_404
        """
        resp = api.get_salon_account(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SALON_ACCOUNT_NOT_FOUND)
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert body["response_type"] == "error"
        assert isinstance(body["data"].get("message"), str)

    def test_license_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/license_get_nonexistent_returns_404
        """
        resp = api.get_license(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_FOUND)

    def test_brand_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/brand_get_nonexistent_returns_404
        """
        resp = api.get_brand(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_BRAND_NOT_FOUND)

    def test_product_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/product_get_nonexistent_returns_404
        """
        resp = api.get_product(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)

    def test_consultant_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/consultant_get_nonexistent_returns_404
        """
        resp = api.get_sales_consultant(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONSULTANT_NOT_FOUND)

    def test_route_plan_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/route_plan_get_nonexistent_returns_404
        """
        resp = api.get_route_plan(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROUTE_PLAN_NOT_FOUND)

    def test_route_stop_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/route_stop_get_nonexistent_returns_404
        """
        resp = api.get_route_stop(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROUTE_STOP_NOT_FOUND)

    def test_order_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/order_get_nonexistent_returns_404
        """
        resp = api.get_order(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_order_item_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/order_item_get_nonexistent_returns_404
        """
        resp = api.get_order_item(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ORDER_ITEM_NOT_FOUND)

    def test_shipment_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/shipment_get_nonexistent_returns_404
        """
        resp = api.get_shipment(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_FOUND)

    def test_promotion_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/promotion_get_nonexistent_returns_404
        """
        resp = api.get_promotion(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROMOTION_NOT_FOUND)

    def test_redemption_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/redemption_get_nonexistent_returns_404
        """
        resp = api.get_promotion_redemption(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REDEMPTION_NOT_FOUND)

    def test_diversion_case_get_nonexistent_returns_404(self, api):
        """PRD §2.8: "**Existence** — path- and body-referenced resource ids
        exist, validated left-to-right along the path, yielding the
        resource-specific `ERR_<RESOURCE>_NOT_FOUND` (404)."

        Design: Corner/entities/diversion_case_get_nonexistent_returns_404
        """
        resp = api.get_diversion_case(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DIVERSION_CASE_NOT_FOUND)

