"""Fiscal-year and airline creation basics: defaults, initial state,
uniqueness constraints, pagination envelope, and read-after-write consistency."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_airline,
    assert_fiscal_year,
    create_airline,
    create_airline_payload,
    create_fiscal_year,
    create_fiscal_year_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]


class TestFiscalYearCreation:
    def test_compensatory_year_defaults_prior_surplus_to_zero(self, api):
        """PRD §3.1: "The carry-forward `prior_year_surplus_cents` is optional
        and defaults to zero; it may be negative, representing a deficit carried
        forward."
        PRD §2.7: "for a compensatory year `prior_year_surplus_cents` defaults
        to zero and plays no part in any derivation."

        Design: Corner/entities/fiscal_year_creation_applies_defaults
        """
        payload = create_fiscal_year_payload(
            year_label="FY_DFLT", methodology="COMPENSATORY",
            airfield_opex_cents=1000000, terminal_opex_cents=500000,
            nonairline_airfield_revenue_cents=0,
            nonairline_terminal_revenue_cents=0,
            terminal_total_space_sqft=100000, forecast_landed_weight_kg=1000)
        del payload["prior_year_surplus_cents"]
        fy = validate_success(api.create_fiscal_year(payload, FINANCE), 201)
        assert_fiscal_year(fy)
        assert fy["prior_year_surplus_cents"] == 0, (
            "Omitted prior_year_surplus_cents defaults to zero")
        assert fy["status"] == "DRAFT", "A new year begins in DRAFT status"
        assert is_valid_uuid(fy["id"]), "id is a bare UUID"
        assert fy["total_projected_landed_weight_kg"] == 0
        assert fy["total_signatory_landed_weight_kg"] == 0
        assert fy["total_rented_space_sqft"] == 0

        fetched = validate_success(api.get_fiscal_year(fy["id"], FINANCE))
        assert fetched["prior_year_surplus_cents"] == 0
        assert fetched["status"] == "DRAFT"

    def test_new_fiscal_year_begins_in_draft(self, api):
        """PRD §3.1: "A new year begins in `DRAFT` status, with its computed
        aggregates `total_projected_landed_weight_kg`,
        `total_signatory_landed_weight_kg`, and `total_rented_space_sqft`
        initialized to zero and its `settlement_id` unset."

        Design: Corner/state_machines/fiscal_year_initial_state_draft
        """
        fy = create_fiscal_year(year_label="FY_INI", airfield_opex_cents=1000,
                                forecast_landed_weight_kg=1000)
        assert fy["status"] == "DRAFT"
        assert fy["settlement_id"] is None, "settlement_id is unset at creation"

        fetched = get_success_data(api.get_fiscal_year(fy["id"], FINANCE))
        assert fetched["status"] == "DRAFT"

    def test_year_label_unique_rejects_duplicate(self, api):
        """PRD §3.1: "The creation payload carries a `year_label` — a unique
        label such as FY2027 that is immutable after creation"
        PRD §2.8: "Field shape follows: a missing required field, a wrong-typed
        value, or an enum value outside its declared set yields
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/fiscal_year_immutable_year_label
        """
        create_fiscal_year(year_label="FY_IMM", airfield_opex_cents=1000)
        resp = api.create_fiscal_year(
            create_fiscal_year_payload(year_label="FY_IMM",
                                       methodology="COMPENSATORY",
                                       airfield_opex_cents=2000),
            FINANCE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_missing_fiscal_year_returns_not_found(self, api):
        """PRD §2.9: "the system validates path identifiers sequentially from
        left to right and rejects the request with `404 Not Found` carrying
        `ERR_NOT_FOUND` at the *first* identifier that does not resolve to an
        existing resource"

        Design: Corner/entities/entity_not_found_returns_404
        """
        resp = api.get_fiscal_year(NON_EXISTENT_UUID, FINANCE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestAirlineCreation:
    def test_iata_code_format_and_uniqueness(self, api):
        """PRD §3.1: "`AirportFinance` registers each **Airline** with an
        `iata_code` — exactly two uppercase letters, unique across carriers — a
        `legal_name`, and a `carrier_class` of `PASSENGER`, `CARGO`, or
        `CHARTER`."
        PRD §2.8: "Field shape follows: a missing required field, a wrong-typed
        value, or an enum value outside its declared set yields
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/airline_iata_code_format_and_uniqueness
        """
        first = create_airline("AA", legal_name="Alpha Air")
        assert_airline(first)

        bad_format = api.create_airline(
            create_airline_payload(iata_code="aa1", legal_name="Bad Code"),
            FINANCE)
        validate_error(bad_format, ApiErrorId.ERR_INVALID_REQUEST)

        duplicate = api.create_airline(
            create_airline_payload(iata_code="AA", legal_name="Duplicate"),
            FINANCE)
        validate_error(duplicate, ApiErrorId.ERR_INVALID_REQUEST)


class TestListingAndEnvelope:
    def test_airline_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and a maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_endpoints_pagination_defaults
        """
        create_airline("LA", legal_name="List One")
        create_airline("LB", legal_name="List Two")
        create_airline("LC", legal_name="List Three")

        data, meta = validate_paginated(api.list_airlines(FINANCE))
        assert len(data) == 3, f"Expected 3 airlines, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10, "default limit is 10"
        assert meta["offset"] == 0, "default offset is 0"

    def test_success_response_envelope_shape(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_shape
        """
        airline = create_airline("EV", legal_name="Envelope Air")

        resp = api.get_airline(airline["id"], FINANCE)
        assert resp.status_code == 200
        body = resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id starts with req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), (
            "api_request_timestamp must be ISO 8601")
        assert body["response_type"] == "object"
        assert body["data"]["id"] == airline["id"]

    def test_created_airline_immediately_visible(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §2.11: "The system does not wait for clients to keep the hierarchy
        coherent."

        Design: Corner/consistency_model/immediate_visibility_after_create
        """
        created = validate_success(
            api.create_airline(
                create_airline_payload(iata_code="IC",
                                       legal_name="Immediate Consistency"),
                FINANCE),
            201,
        )
        fetched = validate_success(api.get_airline(created["id"], FINANCE))
        for field in ("id", "iata_code", "legal_name", "carrier_class",
                      "pfc_approved", "created_at", "updated_at", "version"):
            assert fetched[field] == created[field], (
                f"Field {field} diverged between POST response and GET: "
                f"{created[field]!r} != {fetched[field]!r}")
