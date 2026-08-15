"""Response envelope, pagination, authentication, and role authorization."""
from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR,
    PLANNER,
    ApiErrorId,
    create_packaging_component,
    create_product,
    create_product_payload,
    get_window,
    get_changeover,
    open_changeover,
    create_line,
    create_window,
    validate_error,
    validate_paginated,
)


class TestListPagination:
    def test_products_list_pagination_envelope(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items and defaults to 0."
        PRD §2.3: "the `meta` object of a list response carries `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD §2.3: "Products filter by `product_type`, `brand`, and
        `packaging_component_id`."

        Design: Corner/endpoints/products_list_pagination_envelope
        """
        component = create_packaging_component(qty_on_hand=1000)
        create_product(component["id"], sku_code="P1", name="P1",
                       base_price_cents=100, shelf_life_days=90)
        create_product(component["id"], sku_code="P2", name="P2",
                       base_price_cents=200, shelf_life_days=90)
        create_product(component["id"], sku_code="P3", name="P3",
                       product_type="SEASONAL", base_price_cents=300,
                       shelf_life_days=90)

        data, meta = validate_paginated(api.list_products(PLANNER))
        assert len(data) == 3
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        data, meta = validate_paginated(api.list_products(PLANNER, params={"limit": 2}))
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        data, meta = validate_paginated(
            api.list_products(PLANNER, params={"limit": 2, "offset": 2}))
        assert len(data) == 1
        assert meta["total_count"] == 3
        assert meta["has_more"] is False

        data, meta = validate_paginated(
            api.list_products(PLANNER, params={"product_type": "SEASONAL"}))
        assert len(data) == 1
        assert data[0]["sku_code"] == "P3"

        body = api.list_products(PLANNER).json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["response_type"] == "array"


class TestErrorEnvelope:
    def test_error_envelope_shape_on_not_found(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: "error"" and a `data`
        object carrying "`error_id`" and "`message`".
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/errors/error_envelope_shape_not_found
        """
        resp = api.get_lot(NON_EXISTENT_UUID, PLANNER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)


class TestAuthentication:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request with missing headers, or whose `X-User-Role` does
        not name one of these five roles, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/products_create_missing_auth_header_returns_unauthenticated
        """
        payload = create_product_payload(
            NON_EXISTENT_UUID, sku_code="X", name="X", base_price_cents=100,
            unit_weight_grams=10, shelf_life_days=90)
        resp = api.create_product(payload, {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestExistenceBeforeState:
    def test_cancel_missing_run_returns_404(self, api):
        """PRD §2.6: "Requests that target nested resources are validated left to
        right along the path. The existence of each path identifier is checked in
        order, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first identifier that does not correspond to an existing resource"

        Design: Corner/validations/run_cancel_not_found_returns_404
        """
        resp = api.cancel_run(NON_EXISTENT_UUID, PLANNER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRoleAuthorization:
    def test_window_publish_by_line_operator_forbidden(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §3.4: "Publication is a `PlantManager` act: a `DRAFT` window publishes
        to `PUBLISHED` (from any other state, `ERR_INVALID_STATE`)"

        Design: Corner/rbac/window_publish_by_operator_forbidden
        """
        window = create_window(season_code="HOLIDAY", target_units=1000)
        resp = api.publish_window(window["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_window(window["id"])["status"] == "DRAFT"

    def test_changeover_swab_by_planner_forbidden(self, api):
        """PRD §2.1: "A request whose role is authenticated but not listed among
        the endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE`
        (HTTP 403)."
        PRD §3.3: "a `SanitationLead` records the allergen swab result via a
        payload carrying `swab_passed`."

        Design: Corner/rbac/changeover_swab_by_planner_forbidden
        """
        line = create_line()
        changeover = open_changeover(line["id"], "SHAPE_ONLY")
        resp = api.record_swab(changeover["id"], {"swab_passed": True}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert get_changeover(changeover["id"])["status"] == "PENDING_SWAB"
