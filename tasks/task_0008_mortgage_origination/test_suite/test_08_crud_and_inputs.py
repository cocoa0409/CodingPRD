"""CRUD endpoints, listing, and shape-level input validation.

These tests translate Corner instances drawn from `entities` and `endpoints`.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    create_applicant_payload,
    create_loan_application_payload,
    create_income_verification_payload,
    create_title_search_payload,
    setup_prequalified_loan_application,
    setup_applicant_and_loan_application_draft,
    TEST_USERS,
    ApiErrorId,
)


# =============================================================================
# Queue B — Corner
# =============================================================================

def test_applicant_creation_success_with_all_required_fields(api, lo_headers):
    """PRD §3.1: "A `LoanOfficer` records a new applicant by supplying the
    applicant's `full_name`, a contact `email` whose uniqueness the system
    enforces across all non-archived applicants, the last four digits of the
    applicant's Social Security number as a four-digit string `ssn_last4` used
    as a soft-pull keying token, the applicant's stated `annual_income_cents`
    and `monthly_debt_cents` (both non-negative integer cents), a soft-pull
    `credit_score` that must be at least 300 and at most 850, and the USPS
    two-letter `state_code` of the applicant's residence."

    Design: Corner/entities/applicant_creation_success_with_all_required_fields
    """
    payload = create_applicant_payload(
        full_name="Anna B",
        email="anna.create@test.com",
        ssn_last4="1010",
        annual_income_cents=8_000_000,
        monthly_debt_cents=50_000,
        credit_score=720,
        state_code="CA",
    )
    res = api.create_applicant(payload, lo_headers)
    created = validate_success(res, 201)
    assert created["full_name"] == "Anna B"
    # PRD §2.4 says `version` "begins at 1 (or at whatever the implementation
    # chooses for a freshly created resource)" — accept any positive integer.
    assert isinstance(created["version"], int) and created["version"] >= 1


def test_applicant_missing_required_field_rejected(api, lo_headers):
    """PRD §2.7: "Body-shape problems unrelated to existence (a missing required
    field, an enum value outside its declared set, an integer outside its
    declared range) are rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/applicant_missing_required_field_rejected
    """
    # full_name is required but omitted
    res = api.create_applicant(
        {
            "email": "missing@test.com",
            "ssn_last4": "1111",
            "annual_income_cents": 8_000_000,
            "monthly_debt_cents": 50_000,
            "credit_score": 720,
            "state_code": "CA",
        },
        lo_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# NOTE: A `test_applicant_get_not_found` instance was removed under STEP 1b
# (unique-derivability collapse). PRD §2.7 specifies `ERR_APPLICATION_NOT_FOUND`
# for missing **loan application** path segments and `ERR_APPLICANT_NOT_FOUND`
# for missing **applicant_id foreign-key** referents, but never names which
# error_id applies when a path segment on `/applicants/{id}` is missing.
# A PRD-only reader could reasonably implement that endpoint with either error
# code, so a strict equality assertion against ERR_APPLICATION_NOT_FOUND is
# not uniquely derivable from PRD.


def test_loan_application_invalid_enum_loan_purpose(api, lo_headers):
    """PRD §3.1: "a `loan_purpose` that is either `PURCHASE` or `REFINANCE`"
    PRD §2.7: "an enum value outside its declared set ... rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/loan_application_invalid_enum_loan_purpose
    """
    applicant = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="C",
                email="c.enum@test.com",
                ssn_last4="3010",
                annual_income_cents=8_000_000,
            ),
            lo_headers,
        ),
        201,
    )
    res = api.create_loan_application(
        {
            "applicant_id": applicant["id"],
            "property_address": "X",
            "property_state_code": "CA",
            "loan_purpose": "REMODEL",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 360,
        },
        lo_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_loan_application_invalid_loan_term_months(api, lo_headers):
    """PRD §3.1: "a `loan_term_months` that must be either 180 or 360"
    PRD §2.7: "an integer outside its declared range ... rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)"

    Design: Corner/entities/loan_application_invalid_loan_term_months
    """
    applicant = validate_success(
        api.create_applicant(
            create_applicant_payload(
                full_name="D",
                email="d.term@test.com",
                ssn_last4="4010",
                annual_income_cents=8_000_000,
            ),
            lo_headers,
        ),
        201,
    )
    res = api.create_loan_application(
        {
            "applicant_id": applicant["id"],
            "property_address": "X",
            "property_state_code": "CA",
            "loan_purpose": "PURCHASE",
            "requested_loan_amount_cents": 30_000_000,
            "property_value_cents": 35_000_000,
            "loan_term_months": 240,
        },
        lo_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_applicant_not_found_when_creating_loan_application(api, lo_headers):
    """PRD §2.7: "Foreign-key identifiers in the request body — the
    `applicant_id` on a loan application, or the `application_id` on any
    sub-resource — are validated the same way, and a missing referent is
    rejected with `ERR_APPLICANT_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/applicant_not_found_when_creating_loan_application
    """
    res = api.create_loan_application(
        create_loan_application_payload(
            "00000000-0000-0000-0000-000000000000",
            property_address="X",
            requested_loan_amount_cents=30_000_000,
            property_value_cents=35_000_000,
            loan_term_months=360,
        ),
        lo_headers,
    )
    validate_error(res, ApiErrorId.ERR_APPLICANT_NOT_FOUND.value)


def test_applicant_list_with_pagination_meta(api, lo_headers):
    """PRD §2.3: "Every list endpoint accepts two query parameters that control
    pagination. The `limit` parameter caps the number of items in the page and
    defaults to 10 when omitted; it must be at least 1 and at most 100. The
    `offset` parameter selects how many items to skip from the head of the
    result set and defaults to 0."
    PRD §2.3: "The response envelope's `meta` object on every list response
    carries the four pagination fields `limit`, `offset`, `total_count`, and
    `has_more`."

    Design: Corner/entities/applicant_list_with_pagination_meta
    """
    validate_success(
        api.create_applicant(create_applicant_payload(full_name="L1", email="l1.page@test.com", ssn_last4="5010"), lo_headers),
        201,
    )
    validate_success(
        api.create_applicant(create_applicant_payload(full_name="L2", email="l2.page@test.com", ssn_last4="5011"), lo_headers),
        201,
    )
    validate_success(
        api.create_applicant(create_applicant_payload(full_name="L3", email="l3.page@test.com", ssn_last4="5012"), lo_headers),
        201,
    )

    res = api.list_applicants(lo_headers, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0


def test_income_verification_reject_empty_reason_rejected(api, lo_headers, underwriter_headers):
    """PRD §3.3: "Rejecting a verification requires a non-empty
    `rejection_reason` in the request body; the system records that reason on
    the verification, transitions it from `PENDING` to `REJECTED`, and
    increments its `version`."

    Design: Corner/endpoints/income_verification_reject_empty_reason_rejected
    """
    applicant, app = setup_prequalified_loan_application(
        applicant_overrides={
            "full_name": "IVR",
            "email": "ivr.reject@test.com",
            "ssn_last4": "1190",
            "annual_income_cents": 7_726_104,
        },
    )
    iv = validate_success(
        api.create_income_verification(
            create_income_verification_payload(app["id"]),
            lo_headers,
        ),
        201,
    )
    res = api.reject_income_verification(iv["id"], {"rejection_reason": ""}, underwriter_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    final = validate_success(api.get_income_verification(iv["id"], lo_headers), 200)
    assert final["status"] == "PENDING"


# NOTE: The §1.9 instance title_search_filtered_list_by_application_id is
# skipped under the PRD-first Core rule. PRD §2.3 enumerates exactly two
# list-endpoint query parameters (`limit` and `offset`) for "every list
# endpoint" and never names `application_id` as a filter; a PRD-only reader
# could correctly implement /title-searches without that filter, so unique
# derivability fails (applies_to-scope silence pattern).


def test_error_application_not_found_on_subresource_path(api, lo_headers):
    """PRD §2.7: "If a path segment names a loan application that does not
    exist, the request is rejected with `ERR_APPLICATION_NOT_FOUND` (HTTP 404)
    before any sub-resource segment is examined."

    Design: Corner/errors/error_application_not_found_on_subresource_path
    """
    res = api.prequalify_loan_application("00000000-0000-0000-0000-000000000000", lo_headers)
    validate_error(res, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value)
