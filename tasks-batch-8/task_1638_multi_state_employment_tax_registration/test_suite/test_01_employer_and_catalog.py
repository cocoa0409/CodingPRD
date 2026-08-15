"""Employer singleton, agency catalog, agreements, auth and listing basics."""
from test_helpers import (
    DIRECTOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_employer,
    assert_employer_counter_invariants,
    create_employer,
    create_employer_payload,
    create_reciprocity_agreement,
    create_state_withholding_agency,
    create_tax_agency_payload,
    create_work_location,
    create_work_location_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEmployerSingleton:
    def test_employer_first_create_good_standing_zero_counters(self, api, tax_director_headers):
        """PRD §3.1: "At creation the posture is `GOOD_STANDING` and every counter is zero."

        Design: Corner/entities/employer_singleton_second_create_rejected
        """
        res = api.create_employer(create_employer_payload(), tax_director_headers)
        employer = validate_success(res, 201)
        assert_employer(employer)
        assert_employer_counter_invariants(employer)
        assert employer["compliance_posture"] == "GOOD_STANDING"
        assert employer["open_notice_count"] == 0
        assert employer["outstanding_penalty_cents"] == 0
        assert employer["registered_state_count"] == 0

    def test_employer_second_create_rejected(self, api, tax_director_headers):
        """PRD §3.1: "A second attempt to create the Employer is rejected with
        `ERR_EMPLOYER_ALREADY_EXISTS`."

        Design: Corner/entities/employer_singleton_second_create_rejected
        """
        first = create_employer()
        assert first["compliance_posture"] == "GOOD_STANDING"
        res = api.create_employer(
            create_employer_payload(
                legal_name="Second Corp", fein="987654321", home_state_code="NY"
            ),
            tax_director_headers,
        )
        validate_error(res, ApiErrorId.ERR_EMPLOYER_ALREADY_EXISTS)


class TestTaxAgencyCatalog:
    def test_agency_duplicate_kind_state_locality_rejected(self, api, tax_director_headers):
        """PRD §3.1: "Among active agencies the combination of kind, state, and locality
        must be unique; a duplicate is rejected with `ERR_DUPLICATE_AGENCY`."

        Design: Corner/entities/agency_duplicate_kind_state_locality_rejected
        """
        create_state_withholding_agency(state_code="OR", withholding_rate_bp=500)
        res = api.create_tax_agency(
            create_tax_agency_payload(
                agency_kind="STATE_WITHHOLDING", state_code="OR",
                agency_name="Oregon DOR duplicate", withholding_rate_bp=500,
            ),
            tax_director_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_AGENCY)

    def test_nexus_analyst_cannot_create_agency_forbidden(self, api, nexus_analyst_headers):
        """PRD §2.1: "an attempt to perform an action outside the caller's designated role
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: POST /etax/tax-agencies is authorized for TaxDirector only.

        Design: Corner/validations/nexus_analyst_cannot_create_agency_forbidden
        """
        res = api.create_tax_agency(
            create_tax_agency_payload(
                agency_kind="STATE_WITHHOLDING", state_code="OR",
                agency_name="Oregon DOR", withholding_rate_bp=500,
            ),
            nexus_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


class TestReciprocityAgreementOverlap:
    def test_agreement_starting_on_prior_inclusive_end_rejected(self, api):
        """PRD §3.1: "Two agreements for the same unordered pair whose closed date ranges
        share even a single day are rejected with `ERR_AGREEMENT_OVERLAP`: because both
        endpoints are inclusive, a new agreement's `effective_from` must fall strictly
        after the existing agreement's `effective_to` for the ranges to be disjoint."

        Design: Difficulty/resource_temporal_overlap/agreement_closed_interval_boundary_overlap
        """
        first = create_reciprocity_agreement(
            state_a="PA", state_b="NJ",
            effective_from="2020-01-01T00:00:00Z",
            effective_to="2025-12-31T00:00:00Z",
            certificate_form_code="NJ-165", scope="FULL",
        )
        assert first["status"] == "EXPIRED", (
            "effective_to 2025-12-31 has passed at the default clock 2026-08-01"
        )
        res = api.create_reciprocity_agreement(
            {
                "state_a": "NJ", "state_b": "PA",
                "effective_from": "2025-12-31T00:00:00Z", "scope": "FULL",
            },
            DIRECTOR,
        )
        validate_error(res, ApiErrorId.ERR_AGREEMENT_OVERLAP)

    def test_agreement_starting_day_after_prior_end_created_active(self, api, tax_director_headers):
        """PRD §3.1: "a new agreement's `effective_from` must fall strictly after the
        existing agreement's `effective_to` for the ranges to be disjoint."
        PRD §3.1: "The agreement's `status` is computed from the clock — `SCHEDULED`
        before the first covered date, `ACTIVE` within the covered range, `EXPIRED`
        once the last covered date has passed — and is refreshed by the scheduled sweep."

        Design: Difficulty/resource_temporal_overlap/agreement_closed_interval_boundary_overlap
        """
        first = create_reciprocity_agreement(
            state_a="PA", state_b="NJ",
            effective_from="2020-01-01T00:00:00Z",
            effective_to="2025-12-31T00:00:00Z",
            certificate_form_code="NJ-165", scope="FULL",
        )
        assert first["status"] == "EXPIRED"
        res = api.create_reciprocity_agreement(
            {
                "state_a": "PA", "state_b": "NJ",
                "effective_from": "2026-01-01T00:00:00Z", "scope": "FULL",
            },
            tax_director_headers,
        )
        created = validate_success(res, 201)
        assert created["status"] == "ACTIVE", (
            "open-ended agreement already in force at the default clock 2026-08-01"
        )


class TestAuthAndRequestSanity:
    def test_work_location_create_missing_auth_returns_400(self, api):
        """PRD §2.1: "A request with either header missing or empty is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/work_location_create_missing_auth_returns_400
        """
        res = api.create_work_location(
            create_work_location_payload(state_code="OR", label="No Auth"),
            headers=None,
        )
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_work_location_invalid_enum_rejected(self, api, nexus_analyst_headers):
        """PRD §2.9: "Malformed bodies, invalid enum values, non-positive amounts,
        missing required fields, a notice with no link, an inactive target work
        location, and a certificate-form mismatch fall through to
        `ERR_INVALID_REQUEST` (HTTP 400), the catch-all rejection."

        Design: Corner/errors/work_location_invalid_enum_rejected
        """
        res = api.create_work_location(
            create_work_location_payload(
                state_code="AK", label="Igloo", address_line1="1 Ice Rd",
                city="Anchorage", postal_code="99501", location_type="IGLOO",
            ),
            nexus_analyst_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_auditor_write_attempt_forbidden(self, api, auditor_headers):
        """PRD §2.1: "`Auditor` — a read-only auditor."
        PRD §2.1: "an attempt to perform an action outside the caller's designated role
        is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/auditor_write_attempt_forbidden
        """
        location = create_work_location("OR")
        res = api.create_employee(
            {
                "employee_ref": "E-6001", "full_name": "BF One",
                "resident_state_code": "OR", "hire_date": "2026-08-01T00:00:00Z",
                "annual_wage_cents": 3_000_000,
                "current_work_location_id": location["id"],
            },
            auditor_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_employee_get_nonexistent_returns_not_found(self, api, tax_director_headers):
        """PRD §2.9: "Path identifiers resolve to existing resources, validated left to
        right along the path, and foreign-key identifiers in the request body must
        exist, else `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/employee_get_nonexistent_returns_not_found
        """
        res = api.get_employee(NON_EXISTENT_UUID, tax_director_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)


class TestListPagination:
    def test_list_endpoint_pagination_envelope(self, api, auditor_headers):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
        return. If not provided, it defaults to 10, with a minimum of 1 and a maximum
        of 100. The `offset` parameter specifies the number of items to skip and
        defaults to 0."
        PRD §2.3: "Paginated list-based responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/list_endpoint_pagination_envelope
        """
        create_work_location("OR", label="L1", postal_code="97201",
                             location_type="COMPANY_OFFICE")
        create_work_location("OR", label="L2", postal_code="97202",
                             location_type="CLIENT_SITE")
        create_work_location("NJ", label="L3")
        res = api.list_work_locations(auditor_headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(res)
        assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0
