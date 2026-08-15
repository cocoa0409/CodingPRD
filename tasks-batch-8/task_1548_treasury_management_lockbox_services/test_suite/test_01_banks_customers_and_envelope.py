"""Bank/customer creation defaults, entity retrieval, uniqueness, envelope,
and pagination basics."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_bank,
    assert_customer,
    create_bank,
    create_bank_payload,
    create_customer,
    create_customer_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

IMPLEMENTER = TEST_USERS["implementer_headers"]


class TestBankCreation:
    def test_bank_creation_applies_defaults(self, api, bank_admin_headers):
        """PRD §3.1: "A new bank begins with `posture` `OPERATING`, a
        `current_business_date` of 2026-08-01, and `current_analysis_cycle_index`
        at zero."

        Design: Corner/entities/bank_creation_applies_defaults
        """
        resp = api.create_bank(create_bank_payload(), bank_admin_headers)
        bank = validate_success(resp, 201)
        assert_bank(bank)
        assert bank["current_business_date"] == "2026-08-01"
        assert bank["current_analysis_cycle_index"] == 0
        assert bank["posture"] == "OPERATING"


class TestCustomerCreation:
    def test_customer_creation_sets_prospect_status(self, api):
        """PRD §3.2: "The customer starts as a `PROSPECT` with
        `collected_balance_accumulator_cents` and `days_in_cycle_elapsed` at
        zero."

        Design: Corner/entities/customer_creation_sets_prospect_status
        """
        bank = create_bank()
        resp = api.create_customer(bank["id"], create_customer_payload(),
                                   IMPLEMENTER)
        customer = validate_success(resp, 201)
        assert_customer(customer)
        assert customer["status"] == "PROSPECT"
        assert customer["collected_balance_accumulator_cents"] == 0
        assert customer["days_in_cycle_elapsed"] == 0


class TestRetrieval:
    def test_entity_retrieval_by_id_returns_stored_data(self, api,
                                                        auditor_headers):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §4: "GET | `/banks/{bankId}/customers/{customerId}` | Get a Customer".

        Design: Corner/entities/entity_retrieval_by_id_returns_stored_data
        """
        bank = create_bank()
        created = create_customer(bank["id"], legal_name="Acme Co",
                                  tax_id="12-1", deposit_account_number="DDA-X")
        fetched = validate_success(
            api.get_customer(bank["id"], created["id"], auditor_headers))
        assert_customer(fetched)
        assert fetched["legal_name"] == "Acme Co"
        assert fetched["tax_id"] == "12-1"
        assert fetched["deposit_account_number"] == "DDA-X"

    def test_non_existent_id_returns_not_found(self, api, auditor_headers):
        """PRD §2.6: "Path identifiers are validated left to right: each id in
        a nested path must exist and must belong to the enclosing parent within
        the same bank, and the first failure is rejected with `ERR_NOT_FOUND`
        (HTTP 404)."

        Design: Corner/entities/non_existent_id_returns_not_found
        """
        bank = create_bank()
        resp = api.get_customer(bank["id"], NON_EXISTENT_UUID, auditor_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestUniqueness:
    def test_duplicate_unique_field_rejected(self, api, bank_admin_headers):
        """PRD §3.1: "a nine-digit ABA `routing_number` that is unique across
        banks (a duplicate is refused with `ERR_DUPLICATE_UNIQUE_FIELD`)".

        Design: Corner/entities/duplicate_unique_field_rejected
        """
        create_bank(routing_number="021000089")
        resp = api.create_bank(
            create_bank_payload(legal_name="Second Bank",
                                routing_number="021000089",
                                default_earnings_credit_rate_bp=200),
            bank_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_UNIQUE_FIELD)


class TestResponseEnvelope:
    def test_success_response_envelope_shape(self, api, bank_admin_headers,
                                             auditor_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/success_response_envelope_shape
        """
        bank = create_bank(legal_name="B")
        resp = api.get_bank(bank["id"], auditor_headers)
        data = validate_success(resp, 200)
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert data["legal_name"] == "B"

    def test_error_response_envelope_shape(self, api, auditor_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/error_response_envelope_shape
        """
        bank = create_bank()
        resp = api.get_customer(bank["id"], NON_EXISTENT_UUID, auditor_headers)
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert error_data["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(error_data["message"], str) and error_data["message"]


class TestPagination:
    def test_pagination_defaults_applied(self, api, auditor_headers):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum
        of 100; `offset` defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/pagination_defaults_applied
        """
        bank = create_bank()
        for i in range(15):
            create_customer(bank["id"], legal_name=f"Cust {i + 1}",
                            tax_id=f"12-{i + 1:07d}",
                            deposit_account_number=f"DDA-{i + 1}")
        data, meta = validate_paginated(
            api.list_customers(bank["id"], auditor_headers))
        assert len(data) == 10, "Default limit is 10"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 15
        assert meta["has_more"] is True
