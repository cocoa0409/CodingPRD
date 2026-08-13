"""Response envelope, customer onboarding defaults, and authentication basics."""
from test_helpers import (
    ApiErrorId,
    assert_customer,
    make_customer,
    validate_error,
    validate_success,
)


class TestSuccessEnvelope:
    def test_get_customer_success_envelope_shape(self, api, fleet_manager_headers,
                                                 sales_rep_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" with
        meta.api_request_id, meta.api_request_timestamp, response_type and data;
        "The `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/endpoints/success_envelope_shape
        """
        customer = make_customer(name="Envelope Co", credit_limit_cents=500000)
        resp = api.get_customer(customer["id"], fleet_manager_headers)
        data = validate_success(resp)
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert data["id"] == customer["id"]


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api, fleet_manager_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with response_type "error" and a data object
        carrying error_id and message; "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_unit("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                            fleet_manager_headers)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert error["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(error["message"], str) and error["message"].strip()


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role the
        system does not recognize, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        resp = api.get_unit("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestCustomerOnboarding:
    def test_create_customer_applies_defaults(self, api, sales_rep_headers):
        """PRD §3.1: "A `FleetManager` or `SalesRep` creates a customer with a
        `name`, a `credit_limit_cents`, and an optional `discount_pct` that
        defaults to 0 and must be at least 0 and strictly less than 1" and
        "The new customer begins with `outstanding_balance_cents` and
        `credit_holds_cents` at 0, and its `account_status` begins `ACTIVE`."
        PRD §2.10: "`available_credit_cents` is derived as
        `credit_limit_cents` minus `outstanding_balance_cents` minus
        `credit_holds_cents`".

        Design: Corner/entities/customer_create_applies_defaults
        """
        resp = api.create_customer({"name": "Default Co", "credit_limit_cents": 500000},
                                   sales_rep_headers)
        created = validate_success(resp, 201)
        data = validate_success(api.get_customer(created["id"], sales_rep_headers))
        assert_customer(data)
        assert data["discount_pct"] == 0
        assert data["outstanding_balance_cents"] == 0
        assert data["credit_holds_cents"] == 0
        assert data["available_credit_cents"] == 500000
        assert data["account_status"] == "ACTIVE"

    def test_create_customer_missing_required_name(self, api, sales_rep_headers):
        """PRD §2.6: "request-body shape (required fields present, types correct,
        enum values valid)" is a rejection rung; PRD §5 maps
        `ERR_INVALID_REQUEST` to HTTP 400. PRD §3.1 requires a `name` to create
        a customer.

        Design: Corner/entities/create_customer_missing_required_name
        """
        resp = api.create_customer({"credit_limit_cents": 500000}, sales_rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
