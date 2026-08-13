"""Response envelope shape, list pagination, and authentication-order rules."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_carrier,
    create_product,
    make_accountant_headers,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["admin_headers"]


class TestResponseEnvelope:
    def test_success_and_error_envelope_shapes(self):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_success_and_error
        """
        carrier = create_carrier(name="Carrier ENV", carrier_code="CENV")

        ok_res = api_client.get_carrier(carrier["id"], ADMIN)
        body = ok_res.json()
        assert ok_res.status_code == 200
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert body["data"]["id"] == carrier["id"]

        err_res = api_client.get_carrier(NON_EXISTENT_UUID, ADMIN)
        err_body = err_res.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        validate_error(err_res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestProductListPagination:
    def test_products_list_limit_offset_window(self):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter skips a number of items from the front of the
        result set and defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the response
        envelope."

        Design: Corner/entities/products_list_pagination_envelope
        """
        carrier = create_carrier(name="Carrier PG", carrier_code="CPG")
        for code in ("PG1", "PG2", "PG3"):
            create_product(carrier["id"], product_code=code, name=f"PG {code}")

        page1, meta1 = validate_paginated(
            api_client.list_products(
                ADMIN,
                params={"carrier_id": carrier["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2, f"page 1 must hold 2 items, got {len(page1)}"
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api_client.list_products(
                ADMIN,
                params={"carrier_id": carrier["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1, f"page 2 must hold 1 item, got {len(page2)}"
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestAuthenticationOrder:
    def test_missing_auth_headers_rejected(self):
        """PRD §2.1: "A request missing either header, or carrying a role
        outside this declared set, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_unauthenticated
        """
        res = api_client.list_producers(headers={})
        validate_error(
            res,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )

    def test_role_check_precedes_existence(self):
        """PRD §2.9: "Every request is evaluated against an ordered cascade of
        checks; the earliest failing check determines the error returned, and
        later checks do not run."
        PRD §2.9: "2. **Role authorization** — the caller's role is listed for
        the endpoint, else `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §2.9: "3. **Existence** — path identifiers validated left-to-right,
        then body foreign-key references such as `product_id`, `producer_id`,
        `upline_producer_id`, and `carrier_id`, else `ERR_NOT_FOUND`."

        Design: Corner/validations/forbidden_role_beats_not_found
        """
        res = api_client.terminate_producer(
            NON_EXISTENT_UUID, make_accountant_headers()
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, expected_status=403)
