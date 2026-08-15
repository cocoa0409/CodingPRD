"""Response envelope, pagination defaults, error envelope, and pipeline-1 auth.

Covers the global rules of PRD §2.1-§2.3 that apply uniformly to every endpoint.
"""
from test_helpers import (
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_principal,
    create_principal,
    create_rep_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestResponseEnvelope:
    def test_success_envelope_shape(self, api, auditor_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources." and "The `api_request_id` is a
        server-generated unique identifier for the request that starts with `req_`."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        principal = create_principal()
        resp = api.get_principal(principal["id"], auditor_headers)
        assert resp.status_code == 200, f"GET principal failed: {resp.text}"
        body = resp.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with req_"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == principal["id"]
        assert_principal(body["data"])

    def test_error_envelope_shape(self, api, agency_admin_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard
        envelope format" with response_type "error" and "The `error_id` is a unique,
        machine-readable string that identifies the specific error."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_rep(NON_EXISTENT_UUID, agency_admin_headers)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert error["message"].strip(), "error message must be non-empty"
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestPagination:
    def test_list_pagination_defaults(self, api, auditor_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned
        in one page; it defaults to 10, accepts a minimum of 1, and is capped at 100.
        The `offset` parameter sets how many items to skip before the page begins and
        defaults to 0."

        Design: Corner/endpoints/list_pagination_defaults
        """
        from test_helpers import api_client, TEST_USERS
        admin = TEST_USERS["agency_admin_headers"]
        created = [
            api_client.create_rep(create_rep_payload(display_name=name,
                                                     territory_codes=[code]), admin)
            for name, code in (("R1", "CA"), ("R2", "OR"), ("R3", "WA"))
        ]
        created_ids = {r.json()["data"]["id"] for r in created}

        resp = api.list_reps(auditor_headers)
        assert resp.json()["response_type"] == "array"
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert {r["id"] for r in data} == created_ids


class TestExistenceAndAuthPipeline:
    def test_order_get_not_found_returns_404(self, api, agency_admin_headers):
        """PRD §2.9: "Path identifiers and body reference identifiers (such as
        `customer_id`, `principal_id`, `sample_unit_id`, or `order_id`) resolve to
        existing records — otherwise `ERR_NOT_FOUND`."

        Design: Corner/entities/order_get_not_found_returns_404
        """
        resp = api.get_order(NON_EXISTENT_UUID, agency_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request that is missing either header, that names an unknown
        role, or whose entity-backed identifier does not resolve to an existing record
        is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        payload = {"name": "C1", "spec_territory_code": "CA", "ship_to_territory_code": "WA"}
        resp = api.create_customer(payload, NO_AUTH_HEADERS)
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            expected_status=400,
        )
