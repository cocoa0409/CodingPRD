"""Fiscal-year creation, the CbC threshold boundary, and legal entities."""
from test_helpers import (
    ADMIN,
    TREASURY,
    ApiErrorId,
    assert_fiscal_year,
    assert_legal_entity,
    create_fiscal_year_payload,
    create_legal_entity_payload,
    is_valid_uuid,
    validate_error,
    validate_success,
    api_client,
)


class TestFiscalYearCreation:

    def test_fiscal_year_create_computes_cbc_and_defaults(self):
        """PRD section 3.1: "At creation the server computes `cbc_required`:
        it is true when `group_revenue_eur` is at least 750000000, and the
        boundary is inclusive — exactly 750000000 yields true while 749999999
        yields false. A new fiscal year starts `OPEN` with
        `consolidated_intercompany_net_cents` at 0 and `closed_at` null."
        PRD section 2.4: "`version` (integer): a system-managed integer that
        increments by exactly 1 on every mutation of the resource."

        Design: Corner/entities/fiscal_year_create_computes_cbc_and_defaults
        """
        resp = api_client.create_fiscal_year(
            create_fiscal_year_payload(year_index=2026,
                                       group_revenue_eur=100_000_000),
            ADMIN,
        )
        fy = validate_success(resp, expected_status=201)
        assert_fiscal_year(fy)
        assert fy["status"] == "OPEN"
        assert fy["cbc_required"] is False, \
            "100000000 EUR is below the 750000000 threshold"
        assert fy["consolidated_intercompany_net_cents"] == 0
        assert fy["closed_at"] is None
        assert fy["version"] == 1

    def test_cbc_required_false_one_euro_below_threshold(self):
        """PRD section 3.1: "At creation the server computes `cbc_required`:
        it is true when `group_revenue_eur` is at least 750000000, and the
        boundary is inclusive — exactly 750000000 yields true while 749999999
        yields false."

        Design: Difficulty/boundary_precision_check/cbcr_threshold_inclusive_at_750m
        """
        resp = api_client.create_fiscal_year(
            create_fiscal_year_payload(year_index=2030,
                                       group_revenue_eur=749_999_999),
            ADMIN,
        )
        fy = validate_success(resp, expected_status=201)
        assert_fiscal_year(fy)
        assert fy["cbc_required"] is False, \
            "749999999 EUR must not trigger the CbC obligation"

    def test_cbc_required_true_exactly_at_threshold(self):
        """PRD section 3.1: "At creation the server computes `cbc_required`:
        it is true when `group_revenue_eur` is at least 750000000, and the
        boundary is inclusive — exactly 750000000 yields true while 749999999
        yields false."

        Design: Difficulty/boundary_precision_check/cbcr_threshold_inclusive_at_750m
        """
        resp = api_client.create_fiscal_year(
            create_fiscal_year_payload(year_index=2031,
                                       group_revenue_eur=750_000_000),
            ADMIN,
        )
        fy = validate_success(resp, expected_status=201)
        assert_fiscal_year(fy)
        assert fy["cbc_required"] is True, \
            "exactly 750000000 EUR is the inclusive boundary -> true"


class TestLegalEntityCreation:

    def test_legal_entity_missing_country_code_rejected(self):
        """PRD section 3.1: "A `GroupTaxAdmin` creates each **LegalEntity**
        with a `name`, an ISO 3166-1 alpha-2 `country_code`, and an ISO 4217
        `functional_currency`; it begins `ACTIVE`."
        PRD section 2.8: "**Request-body shape** — required fields present,
        enum values valid, amounts positive where required, and the
        structural rules of each resource."

        Design: Corner/entities/legal_entity_missing_required_field_returns_invalid_request
        """
        resp = api_client.create_legal_entity(
            {"name": "NoCountryCo", "functional_currency": "USD"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_legal_entity_ignores_client_supplied_system_fields(self):
        """PRD section 2.4: "`id` (string): a unique, server-generated
        identifier formatted as a UUID, with no type prefix."
        PRD section 3.1: "A `GroupTaxAdmin` creates each **LegalEntity**
        with a `name`, an ISO 3166-1 alpha-2 `country_code`, and an ISO 4217
        `functional_currency`; it begins `ACTIVE`."

        Design: Corner/entities/entity_system_fields_input_ignored
        """
        supplied_id = "11111111-1111-4111-8111-111111111111"
        resp = api_client.create_legal_entity(
            create_legal_entity_payload(
                name="SysCo", country_code="US", functional_currency="USD",
                id=supplied_id, version=99,
            ),
            ADMIN,
        )
        entity = validate_success(resp, expected_status=201)
        assert_legal_entity(entity)
        assert entity["id"] != supplied_id, "server must mint its own UUID"
        assert is_valid_uuid(entity["id"])
        assert entity["version"] == 1, "client-supplied version is ignored"
        assert entity["status"] == "ACTIVE"


class TestImmediateReadAfterWrite:

    def test_created_entity_immediately_readable(self):
        """PRD section 2.2: "Unless otherwise noted, operations that create
        or modify a resource will return the created or updated resource
        object in the data field."
        PRD section 2.1: "All read endpoints are shared: every one of the
        five roles may call any GET operation."

        Design: Corner/consistency_model/immediate_read_after_write_visibility
        """
        resp = api_client.create_legal_entity(
            create_legal_entity_payload(name="ReadCo", country_code="JP",
                                        functional_currency="JPY"),
            ADMIN,
        )
        created = validate_success(resp, expected_status=201)

        get_resp = api_client.get_legal_entity(created["id"], TREASURY)
        fetched = validate_success(get_resp, expected_status=200)
        assert_legal_entity(fetched)
        assert fetched["id"] == created["id"]
        assert fetched["name"] == "ReadCo"
        assert fetched["country_code"] == "JP"
        assert fetched["status"] == "ACTIVE"
        assert fetched["version"] == 1
