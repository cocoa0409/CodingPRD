"""Dealer creation, reads, response envelope, and request-context rules."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_dealer,
    assert_dealer_floorplan_invariants,
    create_dealer_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestDealerCreationDefaults:

    def test_dealer_creation_applies_defaults_and_system_fields(
            self, api, oem_admin_headers):
        """PRD section 3.1: "A newly created dealer starts in `ONBOARDING` status with `tier` set to `BRONZE`, every computed counter at zero — `floorplan_utilization_cents`, `default_loss_cents`, `chargeback_balance_cents`, `discount_reconciliation_cents`, `parts_purchases_ytd_cents` — `stock_observed_value_cents` at zero, `stock_compliant` false, and `purchases_year` null until the dealer's first recorded parts purchase."
        PRD section 2.4: "**`version`** (integer): a system-managed integer that increments with every modification to the resource."

        Design: Corner/entities/dealer_creation_applies_defaults_and_system_fields
        """
        resp = api.create_dealer(
            create_dealer_payload(
                name="Dealer Z1", dealer_code="DL-Z1", region="West",
                credit_limit_cents=100000, min_stock_value_cents=500,
            ),
            oem_admin_headers,
        )
        created = validate_success(resp, expected_status=201)
        assert_dealer(created)

        dealer = validate_success(api.get_dealer(created["id"],
                                                 oem_admin_headers), 200)
        assert dealer["status"] == "ONBOARDING"
        assert dealer["tier"] == "BRONZE"
        assert dealer["floorplan_utilization_cents"] == 0
        assert dealer["chargeback_balance_cents"] == 0
        assert dealer["discount_reconciliation_cents"] == 0
        assert dealer["parts_purchases_ytd_cents"] == 0
        assert dealer["default_loss_cents"] == 0
        assert dealer["stock_observed_value_cents"] == 0
        assert dealer["stock_compliant"] is False
        assert dealer["purchases_year"] is None
        assert isinstance(dealer["version"], int) and dealer["version"] >= 1
        assert_dealer_floorplan_invariants(dealer)

    def test_dealer_create_missing_required_field_returns_invalid_request(
            self, api, oem_admin_headers):
        """PRD section 2.8: "Required fields must be present, enum values valid, dates parseable, and — where a date range is supplied — the end strictly after the start; a parts return's `return_year` must equal the current clock year (`ERR_INVALID_REQUEST`, `ERR_INVALID_DATE_RANGE`, `ERR_RETURN_YEAR_MISMATCH`)."

        Design: Corner/entities/dealer_create_missing_required_field_returns_invalid_request
        """
        payload = {
            "name": "Dealer Z2",
            "dealer_code": "DL-Z2",
            "region": "West",
            "min_stock_value_cents": 500,
        }
        resp = api.create_dealer(payload, oem_admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        data, meta = validate_paginated(
            api.list_dealers(oem_admin_headers))
        assert meta["total_count"] == 0, (
            "a rejected create must persist nothing, got "
            f"total_count={meta['total_count']}"
        )
        assert data == []

    def test_dealer_get_nonexistent_id_returns_not_found(
            self, api, oem_admin_headers):
        """PRD section 2.8: "Every referenced resource must exist, checked left-to-right: path identifiers first, then identifiers referenced in the request body. The corresponding not-found error is raised for the first missing identifier (`ERR_DEALER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TARGET_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_ADVANCE_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_LEAD_NOT_FOUND`)."

        Design: Corner/entities/dealer_get_nonexistent_id_returns_not_found
        """
        resp = api.get_dealer(NON_EXISTENT_UUID, oem_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DEALER_NOT_FOUND)

    def test_duplicate_dealer_code_rejected(self, api, oem_admin_headers):
        """PRD section 3.1: "The `dealer_code` is unique across all dealers; a collision is rejected with `ERR_DUPLICATE_DEALER_CODE`."

        Design: Corner/entities/duplicate_dealer_code_rejected
        """
        first = api.create_dealer(
            create_dealer_payload(
                name="Dealer Dup", dealer_code="DL-DUP", region="West",
                credit_limit_cents=100000, min_stock_value_cents=0,
            ),
            oem_admin_headers,
        )
        validate_success(first, expected_status=201)

        resp = api.create_dealer(
            create_dealer_payload(
                name="Dealer Dup Two", dealer_code="DL-DUP", region="East",
                credit_limit_cents=200000, min_stock_value_cents=0,
            ),
            oem_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_DEALER_CODE)


class TestResponseEnvelope:

    def test_response_envelope_shape_on_read(self, api, oem_admin_headers):
        """PRD section 2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD section 2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."
        PRD section 2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_shape_on_read
        """
        created = validate_success(
            api.create_dealer(
                create_dealer_payload(
                    name="Dealer EN1", dealer_code="DL-EN1", region="West",
                    credit_limit_cents=100000, min_stock_value_cents=0,
                ),
                oem_admin_headers,
            ),
            expected_status=201,
        )

        resp = api.get_dealer(created["id"], oem_admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["meta"]["api_request_id"], "api_request_id must be present"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["dealer_code"] == "DL-EN1"

    def test_immediate_visibility_after_mutation(self, api, oem_admin_headers):
        """PRD section 1: "All financial amounts are integer cents, all temporal rules are evaluated against a controllable logical clock, and every mutation is immediately visible in the response that commits it."
        PRD section 2.2: "The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_visibility_after_mutation
        """
        created = validate_success(
            api.create_dealer(
                create_dealer_payload(
                    name="Dealer IM1", dealer_code="DL-IM1", region="West",
                    credit_limit_cents=123456, min_stock_value_cents=0,
                ),
                oem_admin_headers,
            ),
            expected_status=201,
        )
        assert created["dealer_code"] == "DL-IM1"
        assert created["credit_limit_cents"] == 123456

        fetched = validate_success(api.get_dealer(created["id"],
                                                  oem_admin_headers), 200)
        assert fetched["dealer_code"] == "DL-IM1"
        assert fetched["credit_limit_cents"] == 123456

        data, meta = validate_paginated(api.list_dealers(oem_admin_headers))
        assert meta["total_count"] == 1
        assert len(data) == 1 and data[0]["id"] == created["id"]


class TestUserContextHeaders:

    def test_dealer_create_missing_auth_header_returns_400(self, api):
        """PRD section 2.1: "Every request must carry `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the operational capacity in which that party acts. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400) before any other processing."

        Design: Corner/validations/dealer_create_missing_auth_header_returns_400
        """
        resp = api.create_dealer(
            {
                "name": "NoAuth",
                "dealer_code": "DL-NA",
                "region": "West",
                "credit_limit_cents": 100000,
                "min_stock_value_cents": 0,
            },
            headers={},
        )
        validate_error(resp,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
