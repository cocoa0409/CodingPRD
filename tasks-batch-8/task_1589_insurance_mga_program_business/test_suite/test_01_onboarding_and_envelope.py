"""Carrier/TPA onboarding, program creation shape, response envelope, 404/401.

Covers corner-design `entities` basics, the response-envelope instance, and the
authentication/ownership priority instances that need no business fixture.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_carrier,
    assert_program,
    assert_tpa,
    create_carrier,
    create_carrier_payload,
    create_program,
    create_program_payload,
    create_tpa,
    create_tpa_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["mga_underwriter_headers"]
FIN = TEST_USERS["mga_finance_headers"]


class TestCarrierOnboarding:
    def test_carrier_create_defaults_active_and_duplicate_naic_rejected(self, api):
        """PRD §3.1: "The `naic_code` is unique across all carriers: an attempt
        to register a code already on file is rejected with `ERR_NAIC_CODE_EXISTS`
        (HTTP 409). A new carrier starts in `ACTIVE` status."

        Design: Corner/entities/carrier_create_success_and_duplicate_naic_rejected
        """
        first = api.create_carrier(create_carrier_payload(naic_code="NAIC-DUP-1"), ADMIN)
        data = validate_success(first, expected_status=201)
        assert_carrier(data)
        assert data["status"] == "ACTIVE"

        dup = api.create_carrier(create_carrier_payload(naic_code="NAIC-DUP-1"), ADMIN)
        validate_error(dup, ApiErrorId.ERR_NAIC_CODE_EXISTS)


class TestTPAOnboarding:
    def test_tpa_duplicate_license_rejected(self, api, platform_admin_headers):
        """PRD §3.1: "The `license_number` is unique across all TPAs; a
        duplicate is rejected with `ERR_LICENSE_NUMBER_EXISTS` (HTTP 409)."

        Design: Corner/entities/tpa_duplicate_license_rejected
        """
        first = api.create_tpa(
            create_tpa_payload(license_number="LIC-DUP-1"), platform_admin_headers)
        data = validate_success(first, expected_status=201)
        assert_tpa(data)
        assert data["status"] == "ACTIVE"

        dup = api.create_tpa(
            create_tpa_payload(license_number="LIC-DUP-1"), platform_admin_headers)
        validate_error(dup, ApiErrorId.ERR_LICENSE_NUMBER_EXISTS)


class TestProgramCreation:
    def test_program_create_missing_required_field_rejected(
            self, api, platform_admin_headers, mga_underwriter_headers):
        """PRD §2.11: "(4) body well-formedness — required fields present, types
        valid, enum members valid, dates parseable, `effective_from` strictly
        before `effective_to`, and amounts positive where required
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/program_create_missing_required_returns_invalid_request
        """
        carrier = create_carrier()
        payload = create_program_payload(carrier["id"])
        del payload["aggregate_limit_cents"]
        resp = api.create_program(payload, mga_underwriter_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        lst = api.list_programs(mga_underwriter_headers,
                                params={"carrier_id": carrier["id"]})
        rows, meta = validate_paginated(lst)
        assert meta["total_count"] == 0

    def test_program_create_invalid_line_of_business_rejected(
            self, api, mga_underwriter_headers):
        """PRD §3.2: "its `line_of_business` (one of `COMMERCIAL_AUTO`,
        `GENERAL_LIABILITY`, `PROPERTY`, `WORKERS_COMPENSATION`, or
        `PROFESSIONAL_LIABILITY`)" — an out-of-enum value is a body
        well-formedness violation (`ERR_INVALID_REQUEST`, PRD §2.11).

        Design: Corner/entities/program_create_invalid_enum_rejected
        """
        carrier = create_carrier()
        payload = create_program_payload(carrier["id"], line_of_business="SPACE_TRAVEL")
        resp = api.create_program(payload, mga_underwriter_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_program_create_ignores_client_supplied_computed_fields(
            self, api, mga_underwriter_headers):
        """PRD §3.2: "A new program starts in `PROPOSED` status with
        `consumed_aggregate_cents` and `trust_balance_cents` at zero,
        `latest_incurred_loss_ratio_pct` null until the first evaluation runs,
        and `termination_reason` null."

        Design: Corner/entities/program_computed_fields_input_ignored
        """
        carrier = create_carrier()
        payload = create_program_payload(
            carrier["id"], status="ACTIVE",
            consumed_aggregate_cents=999999, trust_balance_cents=888888)
        resp = api.create_program(payload, mga_underwriter_headers)
        data = validate_success(resp, expected_status=201)
        assert_program(data)
        assert data["status"] == "PROPOSED"
        assert data["consumed_aggregate_cents"] == 0
        assert data["trust_balance_cents"] == 0
        assert data["latest_incurred_loss_ratio_pct"] is None
        assert data["termination_reason"] is None

    def test_program_initial_state_version_and_counters(
            self, api, mga_underwriter_headers):
        """PRD §3.2: "A new program starts in `PROPOSED` status with
        `consumed_aggregate_cents` and `trust_balance_cents` at zero."
        PRD §2.4: "`version` (integer): a system-managed integer that
        increments with every mutation of the resource" — a freshly created
        resource has version 1.

        Design: Corner/state_machines/program_initial_state_is_proposed
        """
        carrier = create_carrier()
        resp = api.create_program(
            create_program_payload(carrier["id"], line_of_business="PROPERTY"),
            mga_underwriter_headers)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PROPOSED"
        assert data["version"] == 1
        assert data["consumed_aggregate_cents"] == 0
        assert data["trust_balance_cents"] == 0


class TestNotFoundAndAuth:
    def test_get_policy_not_found(self, api, mga_underwriter_headers):
        """PRD §2.11: "(3) existence of every identifier in the path and every
        foreign key in the body (`ERR_NOT_FOUND`)."

        Design: Corner/entities/get_policy_not_found_returns_404
        """
        resp = api.get_policy(NON_EXISTENT_UUID, mga_underwriter_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_request_without_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role
        outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/auth_missing_headers_unauthenticated
        """
        resp = api.list_programs(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_forbidden_role_check_precedes_existence(self, api, mga_finance_headers):
        """PRD §2.11: "The order is: (1) authentication of the headers
        (`ERR_UNAUTHENTICATED`); (2) role permission and entity-backed
        ownership (`ERR_FORBIDDEN`); (3) existence of every identifier in the
        path and every foreign key in the body (`ERR_NOT_FOUND`)."

        Design: Corner/validations/not_found_beats_business_priority_ordering
        """
        # MGAUnderwriter binding a non-existent policy: existence fires (404),
        # not any business rule.
        resp = api.bind_policy(NON_EXISTENT_UUID, UW)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestResponseEnvelope:
    def test_envelope_object_and_array_shapes(self, api, mga_finance_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources." and "Pagination-related
        fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are
        included for list endpoints."

        Design: Corner/endpoints/get_response_envelope_shape
        """
        carrier = create_carrier()
        single = api.get_carrier(carrier["id"], mga_finance_headers)
        body = validate_success(single)
        assert single.json()["response_type"] == "object"
        assert body["id"] == carrier["id"]
        meta = single.json()["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in meta

        lst = api.list_carriers(mga_finance_headers)
        rows, meta = validate_paginated(lst)
        assert lst.json()["response_type"] == "array"
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] >= 1
        assert isinstance(meta["has_more"], bool)
