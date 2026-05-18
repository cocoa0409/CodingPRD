"""Petitioner and Beneficiary CRUD — PRD §3.1.

Coverage:
- Create petitioner with required fields; check envelope shape.
- Optional a_number default = null.
- Beneficiary creation under the path's petitioner.
- ERR_VALIDATION on missing required fields / bad enums.
- ERR_NOT_FOUND on fetch of non-existent petitioner/beneficiary.
- Ownership rules: a Petitioner can only act on their OWN petitioner /
  cases — PRD §3.1.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_beneficiary,
    assert_petitioner,
    create_beneficiary,
    create_beneficiary_payload,
    create_petitioner,
    create_petitioner_payload,
    make_beneficiary_headers,
    make_petitioner_headers,
    random_a_number,
    random_email,
    random_suffix,
    setup_petitioner_and_beneficiary,
    validate_error,
    validate_success,
)


# ===========================================================================
# Petitioner — happy path
# ===========================================================================
class TestPetitionerCreate:

    def test_create_petitioner_minimum_required_fields(
        self, api, officer_headers,
    ):
        """PRD §3.1: "The petitioner supplies a full_name between 1 and
        120 characters, a date_of_birth expressed as an ISO 8601
        calendar date in YYYY-MM-DD form that must fall at least
        fourteen years before today, a country_of_citizenship written
        as a three-letter uppercase ISO 3166-1 alpha-3 country code,
        and an email address conforming to RFC 5322 for officer
        correspondence."

        Claim: posting the four required fields yields 201 + a valid
        Petitioner envelope.
        """
        payload = create_petitioner_payload()
        resp = api_client.create_petitioner(payload, officer_headers)
        data = validate_success(resp, expected_status=201)
        assert_petitioner(data)
        assert data["full_name"] == payload["full_name"]
        assert data["email"] == payload["email"]

    def test_a_number_absent_defaults_to_null(
        self, api, officer_headers,
    ):
        """PRD §3.1: "An optional a_number may be supplied for
        petitioners who already hold an Alien Registration Number; when
        present it must match the pattern of a capital A followed by
        exactly nine digits, and when absent the value defaults to
        null."

        Claim: omitting a_number causes the persisted value to be null.
        """
        payload = create_petitioner_payload()
        # ensure absent in payload
        payload.pop("a_number", None)
        resp = api_client.create_petitioner(payload, officer_headers)
        data = validate_success(resp, expected_status=201)
        assert data.get("a_number") is None, (
            f"a_number must default to null when absent, got "
            f"{data.get('a_number')!r}"
        )

    def test_a_number_present_validated(self, api, officer_headers):
        """PRD §3.1: "when present it must match the pattern of a
        capital A followed by exactly nine digits".

        Claim: providing a valid a_number is accepted and round-trips.
        """
        a_no = random_a_number()
        payload = create_petitioner_payload(a_number=a_no)
        resp = api_client.create_petitioner(payload, officer_headers)
        data = validate_success(resp, expected_status=201)
        assert data["a_number"] == a_no


class TestPetitionerCreateRejected:

    @pytest.mark.parametrize(
        "missing_field",
        ["full_name", "date_of_birth", "country_of_citizenship", "email"],
    )
    def test_missing_required_field_rejected(
        self, api, officer_headers, missing_field,
    ):
        """PRD §3.1: "The petitioner supplies a full_name between 1 and
        120 characters, a date_of_birth expressed as an ISO 8601
        calendar date in YYYY-MM-DD form that must fall at least
        fourteen years before today, a country_of_citizenship written
        as a three-letter uppercase ISO 3166-1 alpha-3 country code,
        and an email address conforming to RFC 5322 for officer
        correspondence."

        Claim: omitting any required field -> ERR_VALIDATION.
        """
        payload = create_petitioner_payload()
        payload.pop(missing_field)
        resp = api_client.create_petitioner(payload, officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_country_of_citizenship_must_be_three_uppercase(
        self, api, officer_headers,
    ):
        """PRD §3.1: "country_of_citizenship written as a three-letter
        uppercase ISO 3166-1 alpha-3 country code".

        Claim: a lowercase / 2-letter country code -> ERR_VALIDATION.
        """
        payload = create_petitioner_payload(country_of_citizenship="us")
        resp = api_client.create_petitioner(payload, officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_dob_under_14_years_rejected(self, api, officer_headers):
        """PRD §3.1: "a date_of_birth expressed as an ISO 8601 calendar
        date in YYYY-MM-DD form that must fall at least fourteen years
        before today".

        Claim: a date-of-birth less than 14 years before today ->
        ERR_VALIDATION.
        """
        from datetime import date, timedelta
        recent = date.today() - timedelta(days=365 * 5)
        payload = create_petitioner_payload(
            date_of_birth=recent.isoformat(),
        )
        resp = api_client.create_petitioner(payload, officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Petitioner — fetch and ownership
# ===========================================================================
class TestPetitionerFetch:

    def test_get_existing_petitioner(self, api, officer_headers):
        """PRD §4: GET /petitioners/{petitioner_id} returns 200 and the
        Petitioner resource.

        Claim: a freshly-created petitioner is retrievable.
        """
        p = create_petitioner()
        resp = api_client.get_petitioner(p["id"], officer_headers)
        data = validate_success(resp)
        assert_petitioner(data)
        assert data["id"] == p["id"]

    def test_get_nonexistent_petitioner_404(self, api, officer_headers):
        """PRD §2.4: "Path-resource existence — every path segment is
        resolved left to right ... any unresolved segment yields
        ERR_NOT_FOUND."

        Claim: unknown petitioner_id -> ERR_NOT_FOUND.
        """
        resp = api_client.get_petitioner(NON_EXISTENT_UUID, officer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_petitioner_cannot_read_other_petitioner(self, api):
        """PRD §3.1: "A Petitioner may create only their own petitioner
        record (their X-User-ID becomes its id), only beneficiaries
        under that own petitioner, and only cases referencing that own
        petitioner; an attempt to act on another petitioner's
        resources is rejected with ERR_FORBIDDEN."

        Claim: a Petitioner reading another petitioner's record ->
        ERR_FORBIDDEN. We mint headers for petitioner B but try to
        read petitioner A.
        """
        p_a = create_petitioner()
        p_b = create_petitioner()
        # Act as petitioner B reading A.
        resp = api_client.get_petitioner(
            p_a["id"], make_petitioner_headers(p_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Beneficiary — creation & ownership
# ===========================================================================
class TestBeneficiaryCreate:

    def test_create_beneficiary_under_petitioner(
        self, api, officer_headers,
    ):
        """PRD §3.1: "Under that petitioner, the sponsor registers one
        or more Beneficiary profiles. A beneficiary record carries its
        own full_name (also between 1 and 120 characters),
        date_of_birth as an ISO 8601 date, country_of_chargeability as
        a three-letter uppercase ISO 3166-1 alpha-3 code that the
        visa-bulletin lookup will consult, a preference_category
        selected from F1, F2A, F2B, F3, F4, or IR ..."

        Claim: posting the 5 required fields under a petitioner yields
        201 + a valid Beneficiary.
        """
        p = create_petitioner()
        payload = create_beneficiary_payload()
        resp = api_client.create_beneficiary(p["id"], payload, officer_headers)
        data = validate_success(resp, expected_status=201)
        assert_beneficiary(data)
        assert data["petitioner_id"] == p["id"]

    @pytest.mark.parametrize(
        "missing_field",
        [
            "full_name", "date_of_birth", "country_of_chargeability",
            "preference_category", "relationship_to_petitioner",
        ],
    )
    def test_missing_required_field_rejected(
        self, api, officer_headers, missing_field,
    ):
        """PRD §3.1: required beneficiary fields.

        Claim: omitting any required field -> ERR_VALIDATION.
        """
        p = create_petitioner()
        payload = create_beneficiary_payload()
        payload.pop(missing_field)
        resp = api_client.create_beneficiary(p["id"], payload, officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_invalid_preference_category_rejected(
        self, api, officer_headers,
    ):
        """PRD §3.1: "a preference_category selected from F1, F2A, F2B,
        F3, F4, or IR".

        Claim: an out-of-set preference_category -> ERR_VALIDATION.
        """
        p = create_petitioner()
        payload = create_beneficiary_payload(preference_category="F5")
        resp = api_client.create_beneficiary(p["id"], payload, officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_invalid_relationship_rejected(self, api, officer_headers):
        """PRD §3.1: "a relationship_to_petitioner chosen from SPOUSE,
        CHILD, PARENT, SIBLING, or FIANCE".

        Claim: an out-of-set relationship -> ERR_VALIDATION.
        """
        p = create_petitioner()
        payload = create_beneficiary_payload(
            relationship_to_petitioner="COUSIN",
        )
        resp = api_client.create_beneficiary(p["id"], payload, officer_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_petitioner_not_found_on_creation(
        self, api, officer_headers,
    ):
        """PRD §2.4: "every path segment is resolved left to right ...
        any unresolved segment yields ERR_NOT_FOUND."

        Claim: POST under a non-existent petitioner_id -> ERR_NOT_FOUND.
        """
        payload = create_beneficiary_payload()
        resp = api_client.create_beneficiary(
            NON_EXISTENT_UUID, payload, officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestBeneficiaryFetch:

    def test_get_existing_beneficiary(self, api, officer_headers):
        """PRD §4: GET /beneficiaries/{beneficiary_id} returns the
        Beneficiary.

        Claim: a freshly-created beneficiary is retrievable.
        """
        _, b = setup_petitioner_and_beneficiary()
        resp = api_client.get_beneficiary(b["id"], officer_headers)
        data = validate_success(resp)
        assert_beneficiary(data)
        assert data["id"] == b["id"]

    def test_get_nonexistent_beneficiary_404(
        self, api, officer_headers,
    ):
        """PRD §2.4: missing path resource -> ERR_NOT_FOUND.

        Claim: unknown beneficiary_id -> ERR_NOT_FOUND.
        """
        resp = api_client.get_beneficiary(
            NON_EXISTENT_UUID, officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_beneficiary_can_fetch_self(self, api):
        """PRD §2.1: "A Beneficiary may fetch their own beneficiary
        record and read or respond on cases where they are the
        beneficiary."

        Claim: a Beneficiary with X-User-ID == beneficiary.id may GET
        /beneficiaries/{id} for themselves.
        """
        _, b = setup_petitioner_and_beneficiary()
        resp = api_client.get_beneficiary(
            b["id"], make_beneficiary_headers(b["id"]),
        )
        data = validate_success(resp)
        assert data["id"] == b["id"]
