"""Customers, response envelope, and pagination basics."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_customer,
    create_customer,
    get_success_data,
    make_customer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCustomerDefaults:
    def test_customer_creation_applies_defaults(self, api, plant_manager_headers):
        """PRD §3.1: "a `credit_limit_cents` expressed in integer cents, and
        optionally a `default_tolerance_pct` used to set the overrun/underrun
        tolerance on each accepted job; when omitted, `default_tolerance_pct`
        is 5." A fresh customer has exposure 0 and posture ACTIVE.

        Design: Corner/entities/customer_creation_applies_defaults
        """
        resp = api.create_customer(
            {"name": "Default Cust", "credit_limit_cents": 1000000},
            plant_manager_headers,
        )
        data = validate_success(resp, 201)
        assert_customer(data)
        assert data["default_tolerance_pct"] == 5, (
            f"expected default tolerance 5, got {data['default_tolerance_pct']}"
        )
        assert data["exposure_cents"] == 0
        assert data["posture"] == "ACTIVE"
        assert data["reprint_credit_balance_cents"] == 0
        assert data["version"] == 1

    def test_customer_defaults_posture_gate_baseline(self, api, plant_manager_headers):
        """PRD §3.1: "The customer's `posture` is `ACTIVE` when
        `exposure_cents` is less than or equal to `credit_limit_cents`" — a
        new customer starts at zero exposure, hence ACTIVE.

        Design: Corner/entities/customer_creation_applies_defaults
        """
        cust = create_customer(name="Gate", credit_limit_cents=1)
        assert cust["posture"] == "ACTIVE"
        assert cust["exposure_cents"] == 0 <= cust["credit_limit_cents"]


class TestCustomerValidation:
    def test_customer_create_missing_required_name(self, api, plant_manager_headers):
        """PRD §2.7: "generic field-level request validity — missing required
        fields, bad enums, out-of-range numerics, malformed payloads — is
        enforced with `ERR_VALIDATION` (HTTP 400)."

        Design: Corner/entities/customer_create_missing_required_name
        """
        resp = api.create_customer({"credit_limit_cents": 1000}, plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestNotFound:
    def test_job_get_not_found_returns_404(self, api, plant_manager_headers):
        """PRD §2.7: "path parameters and body foreign-key references must
        resolve to existing resources... with the first unresolved reference
        producing `ERR_NOT_FOUND`."

        Design: Corner/entities/job_get_not_found_returns_404
        """
        resp = api.get_job(NON_EXISTENT_UUID, plant_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPagination:
    def test_customer_list_pagination_defaults(self, api, plant_manager_headers):
        """PRD §2.3: "The `meta` object of a list response carries exactly four
        pagination fields: `limit`, `offset`, `total_count`, and `has_more`."
        and §2.2: "`response_type` is either \"object\" for a single resource or
        \"array\" for a list of resources."

        Design: Corner/entities/customer_list_pagination_defaults
        """
        for i in range(3):
            create_customer(name=f"C{i+1}", credit_limit_cents=1000)
        resp = api.list_customers(plant_manager_headers, params={"limit": 2, "offset": 0})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
        assert meta["has_more"] is True
        assert len(rows) == 2
        assert meta["limit"] == 2 and meta["offset"] == 0

    def test_customer_list_omitted_limit_defaults_to_10(self, api, plant_manager_headers):
        """PRD §2.3: "The `limit` parameter controls the maximum number of
        items returned; if omitted, it defaults to 10."

        Design: Corner/entities/customer_list_pagination_defaults
        """
        for i in range(12):
            create_customer(name=f"D{i}", credit_limit_cents=1000)
        resp = api.list_customers(plant_manager_headers)
        rows, meta = validate_paginated(resp)
        assert meta["limit"] == 10
        assert len(rows) == 10
        assert meta["total_count"] == 12
        assert meta["has_more"] is True


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api, plant_manager_headers):
        """PRD §2.2: error responses carry `response_type` "error" and
        "`error_id` is a unique, machine-readable string"; "The `meta` object
        for error responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_job(NON_EXISTENT_UUID, plant_manager_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]

    def test_success_envelope_shape(self, api, plant_manager_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either \"object\" for a single resource or
        \"array\" for a list of resources."

        Design: Corner/endpoints/error_envelope_shape
        """
        cust = create_customer(name="Env", credit_limit_cents=100)
        resp = api.get_customer(cust["id"], plant_manager_headers)
        body = resp.json()
        assert resp.status_code == 200
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body["data"]["id"] == cust["id"]
