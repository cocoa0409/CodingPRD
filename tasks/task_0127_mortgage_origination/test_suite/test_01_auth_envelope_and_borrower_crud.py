"""Auth header contract, response envelope, Borrower and
LoanApplication CRUD basics, and pagination (PRD §2.1, §2.2, §2.3,
§2.4, §3.1)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_borrower,
    assert_loan_application,
    build_user_headers,
    create_borrower,
    create_borrower_and_application,
    create_borrower_payload,
    create_loan_application_payload,
    make_borrower_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth headers — PRD §2.1
# ===========================================================================
def test_missing_both_auth_headers_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the system
    rejects the request with ERR_AUTH_REQUIRED."

    Claim: POST with no X-User-ID and no X-User-Role -> 401
    ERR_AUTH_REQUIRED.
    """
    res = api.create_borrower(
        create_borrower_payload(),
        headers={"Content-Type": "application/json"},
    )
    validate_error(
        res, ApiErrorId.ERR_AUTH_REQUIRED.value, expected_status=401,
    )


def test_missing_user_id_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the system
    rejects the request with ERR_AUTH_REQUIRED."

    Claim: missing X-User-ID alone -> ERR_AUTH_REQUIRED.
    """
    res = api.create_borrower(
        create_borrower_payload(),
        headers={
            "X-User-Role": "LoanOfficer",
            "Content-Type": "application/json",
        },
    )
    validate_error(
        res, ApiErrorId.ERR_AUTH_REQUIRED.value, expected_status=401,
    )


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the system
    rejects the request with ERR_AUTH_REQUIRED."

    Claim: missing X-User-Role alone -> ERR_AUTH_REQUIRED.
    """
    res = api.create_borrower(
        create_borrower_payload(),
        headers={
            "X-User-ID": "lo-001",
            "Content-Type": "application/json",
        },
    )
    validate_error(
        res, ApiErrorId.ERR_AUTH_REQUIRED.value, expected_status=401,
    )


def test_empty_user_id_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the system
    rejects the request with ERR_AUTH_REQUIRED."

    Claim: empty X-User-ID -> ERR_AUTH_REQUIRED.
    """
    res = api.create_borrower(
        create_borrower_payload(),
        headers={
            "X-User-ID": "",
            "X-User-Role": "LoanOfficer",
            "Content-Type": "application/json",
        },
    )
    validate_error(
        res, ApiErrorId.ERR_AUTH_REQUIRED.value, expected_status=401,
    )


def test_unknown_role_string_rejected(api):
    """PRD §2.1: "If the supplied role string is not one of the four
    recognised roles, the request is rejected with ERR_FORBIDDEN_ROLE."

    Claim: X-User-Role=SuperAdmin -> ERR_FORBIDDEN_ROLE.
    """
    res = api.create_borrower(
        create_borrower_payload(),
        headers={
            "X-User-ID": "x",
            "X-User-Role": "SuperAdmin",
            "Content-Type": "application/json",
        },
    )
    validate_error(
        res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403,
    )


def test_borrower_role_cannot_create_borrower(api):
    """PRD §4: POST /borrowers authorised for LoanOfficer or Admin
    only. A Borrower role attempting POST /borrowers must be rejected.

    PRD §2.1: "An authenticated request whose role is recognised but not
    authorised for the requested operation is rejected with
    ERR_FORBIDDEN_ROLE."
    """
    res = api.create_borrower(
        create_borrower_payload(),
        headers=TEST_USERS["borrower_fallback_headers"],
    )
    validate_error(
        res, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403,
    )


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
def test_success_response_envelope_shape(api, loan_officer_headers):
    """PRD §2.2: success envelope has meta.api_request_id (req_*),
    meta.api_request_timestamp (ISO 8601 UTC with three fractional
    digits), response_type ("object" or "array"), and data.

    Claim: a 201 success response carries these fields with the right
    shapes.
    """
    res = api.create_borrower(
        create_borrower_payload(), loan_officer_headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert "meta" in body
    assert "response_type" in body
    assert "data" in body
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        "PRD §2.2: api_request_id must start with 'req_'"
    )
    assert isinstance(meta.get("api_request_timestamp"), str)
    assert body["response_type"] in ("object", "array")


def test_error_response_envelope_shape(api, loan_officer_headers):
    """PRD §2.2: error envelope carries response_type 'error' and
    data.error_id + data.message.

    Claim: a 404 on GET /borrowers/{non_existent} returns the error
    envelope.
    """
    res = api.get_borrower(NON_EXISTENT_UUID, loan_officer_headers)
    assert res.status_code >= 400
    body = res.json()
    assert body.get("response_type") == "error", (
        "PRD §2.2: error envelope response_type must be 'error'"
    )
    assert "error_id" in body.get("data", {})
    assert "message" in body.get("data", {})


# ===========================================================================
# Borrower CRUD — PRD §3.1
# ===========================================================================
def test_create_borrower_returns_valid_entity(api, loan_officer_headers):
    """PRD §3.1: "The borrower payload carries five intake fields: the
    borrower's full_name, the last four digits of their Social Security
    Number in ssn_last4 (exactly four numeric characters), their stated
    annual_income_cents (a non-negative integer in cents), their
    tri-merge FICO credit_score at intake (which must lie between 300
    and 850 inclusive), and the two-letter US state_code for the
    subject property's location."

    Claim: a well-formed POST /borrowers returns a Borrower entity with
    all five inputs preserved, plus PRD §2.4 common fields.
    """
    res = api.create_borrower(
        create_borrower_payload(
            full_name="Jane Smith",
            ssn_last4="9876",
            annual_income_cents=12_000_000,
            credit_score=720,
            state_code="CA",
        ),
        loan_officer_headers,
    )
    b = validate_success(res, 201)
    assert_borrower(b)
    assert b["full_name"] == "Jane Smith"
    assert b["ssn_last4"] == "9876"
    assert b["annual_income_cents"] == 12_000_000
    assert b["credit_score"] == 720
    assert b["state_code"] == "CA"
    assert b["version"] == 1


def test_get_borrower_round_trip(api, loan_officer_headers):
    """PRD §3.1 + §2.4: a created Borrower can be retrieved by id.

    Claim: POST /borrowers returns an id; GET /borrowers/{id} returns
    an equivalent record.
    """
    b = create_borrower(headers=loan_officer_headers)
    res = api.get_borrower(b["id"], loan_officer_headers)
    got = validate_success(res, 200)
    assert got["id"] == b["id"]
    assert got["full_name"] == b["full_name"]


def test_get_nonexistent_borrower_returns_404(api, loan_officer_headers):
    """PRD §2.5: the borrower endpoints are not nested under loan
    applications, so a missing borrower id should surface as 404.

    Claim: GET /borrowers/{nonexistent_uuid} -> 404. We accept either
    ERR_APPLICATION_NOT_FOUND or ERR_RESOURCE_NOT_FOUND depending on
    how the implementation categorises a missing borrower — the PRD
    does not name a specific code for "Borrower not found" at this
    endpoint.
    """
    res = api.get_borrower(NON_EXISTENT_UUID, loan_officer_headers)
    assert res.status_code == 404, (
        f"Expected 404 for non-existent borrower, got {res.status_code}"
    )


@pytest.mark.parametrize("bad_score", [299, 851, 0, -1, 1000])
def test_credit_score_out_of_range_rejected(
    api, loan_officer_headers, bad_score,
):
    """PRD §3.1: "credit_score at intake (which must lie between 300
    and 850 inclusive)".

    Claim: a credit_score outside [300, 850] is rejected with
    ERR_VALIDATION.
    """
    res = api.create_borrower(
        create_borrower_payload(credit_score=bad_score),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_VALIDATION.value, expected_status=422,
    )


@pytest.mark.parametrize("bad_ssn", ["123", "12345", "abcd", "12a4", ""])
def test_ssn_last4_invalid_rejected(
    api, loan_officer_headers, bad_ssn,
):
    """PRD §3.1: "ssn_last4 (exactly four numeric characters)".

    Claim: ssn_last4 that is not exactly four numeric chars is rejected
    with ERR_VALIDATION.
    """
    res = api.create_borrower(
        create_borrower_payload(ssn_last4=bad_ssn),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_VALIDATION.value, expected_status=422,
    )


def test_negative_annual_income_rejected(api, loan_officer_headers):
    """PRD §3.1: "annual_income_cents (a non-negative integer in
    cents)".

    Claim: a negative annual_income_cents is rejected with
    ERR_VALIDATION.
    """
    res = api.create_borrower(
        create_borrower_payload(annual_income_cents=-1),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_VALIDATION.value, expected_status=422,
    )


# ===========================================================================
# Loan application CRUD — PRD §3.1
# ===========================================================================
def test_create_loan_application_returns_intake(api, loan_officer_headers):
    """PRD §3.1: "A newly created application enters the lifecycle in
    INTAKE. The computed fields counter_offered_amount_cents, dti_ratio,
    ltv_ratio, compliance_reviewer_id, trid_clock_started_at, and
    closing_eligible_at are all null at creation; pmi_required defaults
    to false."

    Claim: POST /loan-applications -> status=INTAKE, pmi_required=false,
    and the listed computed fields are null.
    """
    borrower = create_borrower(headers=loan_officer_headers)
    res = api.create_loan_application(
        create_loan_application_payload(borrower_id=borrower["id"]),
        loan_officer_headers,
    )
    app = validate_success(res, 201)
    assert_loan_application(app)
    assert app["status"] == "INTAKE"
    assert app["pmi_required"] is False
    assert app.get("counter_offered_amount_cents") is None
    assert app.get("dti_ratio") is None
    assert app.get("ltv_ratio") is None
    assert app.get("compliance_reviewer_id") is None
    assert app.get("trid_clock_started_at") is None
    assert app.get("closing_eligible_at") is None


def test_requested_loan_amount_exceeding_sale_price_rejected(
    api, loan_officer_headers,
):
    """PRD §3.1: "the requested_loan_amount_cents (also strictly
    positive and not exceeding sale_price_cents)".

    Claim: requested > sale_price -> ERR_VALIDATION.
    """
    borrower = create_borrower(headers=loan_officer_headers)
    res = api.create_loan_application(
        create_loan_application_payload(
            borrower_id=borrower["id"],
            sale_price_cents=40_000_000,
            requested_loan_amount_cents=40_000_001,
        ),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_VALIDATION.value, expected_status=422,
    )


@pytest.mark.parametrize("bad_term", [60, 100, 121, 359, 361, 720])
def test_invalid_loan_term_rejected(
    api, loan_officer_headers, bad_term,
):
    """PRD §3.1: "loan_term_months (one of 120, 180, 240, or 360)".

    Claim: a loan_term_months not in {120, 180, 240, 360} is rejected
    with ERR_VALIDATION.
    """
    borrower = create_borrower(headers=loan_officer_headers)
    res = api.create_loan_application(
        create_loan_application_payload(
            borrower_id=borrower["id"],
            loan_term_months=bad_term,
        ),
        loan_officer_headers,
    )
    validate_error(
        res, ApiErrorId.ERR_VALIDATION.value, expected_status=422,
    )


def test_get_nonexistent_application_returns_app_not_found(
    api, loan_officer_headers,
):
    """PRD §2.5: "The system first confirms that the LoanApplication
    referenced by the leftmost identifier exists; if it does not, the
    request is rejected with ERR_APPLICATION_NOT_FOUND."

    Claim: GET /loan-applications/{nonexistent} -> 404
    ERR_APPLICATION_NOT_FOUND.
    """
    res = api.get_loan_application(NON_EXISTENT_UUID, loan_officer_headers)
    validate_error(
        res,
        ApiErrorId.ERR_APPLICATION_NOT_FOUND.value,
        expected_status=404,
    )


def test_nested_resource_not_found_under_existing_app(
    api, loan_officer_headers,
):
    """PRD §2.5: "Only after the parent application is located does the
    system look for the nested resource ...; if that nested record is
    absent or not parented to the resolved application, the response is
    ERR_RESOURCE_NOT_FOUND."

    Claim: hitting a verify endpoint with a non-existent
    income-verification id under an existing application returns
    ERR_RESOURCE_NOT_FOUND, not ERR_APPLICATION_NOT_FOUND.
    """
    _, app = create_borrower_and_application(headers=loan_officer_headers)
    res = api.verify_income(
        app["id"], NON_EXISTENT_UUID, None, loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_RESOURCE_NOT_FOUND.value,
        expected_status=404,
    )


def test_nested_resource_lookup_left_to_right_ordering(
    api, loan_officer_headers,
):
    """PRD §2.5: "URL paths that contain multiple resource identifiers
    are validated left-to-right. The system first confirms that the
    LoanApplication referenced by the leftmost identifier exists; if
    it does not, the request is rejected with
    ERR_APPLICATION_NOT_FOUND before any further check."

    Claim: a non-existent application id AND a non-existent nested id
    surface as ERR_APPLICATION_NOT_FOUND, not ERR_RESOURCE_NOT_FOUND.
    """
    res = api.verify_income(
        NON_EXISTENT_UUID, NON_EXISTENT_UUID, None, loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_APPLICATION_NOT_FOUND.value,
        expected_status=404,
    )


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
def test_list_applications_returns_paginated_envelope(
    api, loan_officer_headers,
):
    """PRD §2.3: "Every list response includes four fields in the meta
    object of the envelope: limit, offset, total_count, and has_more."

    Claim: GET /loan-applications returns a paginated envelope with
    the four pagination meta fields populated.
    """
    # Create three applications so pagination is meaningful.
    for _ in range(3):
        create_borrower_and_application(headers=loan_officer_headers)
    res = api.list_loan_applications(loan_officer_headers)
    data, meta = validate_paginated(res)
    assert "limit" in meta
    assert "offset" in meta
    assert "total_count" in meta
    assert "has_more" in meta
    assert meta["total_count"] >= 3


def test_list_applications_default_limit_is_10(api, loan_officer_headers):
    """PRD §2.3: "When omitted, limit defaults to 10."

    Claim: with no limit param, meta.limit == 10.
    """
    create_borrower_and_application(headers=loan_officer_headers)
    res = api.list_loan_applications(loan_officer_headers)
    _, meta = validate_paginated(res)
    assert meta["limit"] == 10


def test_list_applications_offset_beyond_returns_empty(
    api, loan_officer_headers,
):
    """PRD §2.3: list endpoints accept limit and offset.

    Claim: offset beyond total_count returns no rows.
    """
    create_borrower_and_application(headers=loan_officer_headers)
    res = api.list_loan_applications(
        loan_officer_headers, params={"offset": 9999},
    )
    data, meta = validate_paginated(res)
    assert len(data) == 0
    assert meta["has_more"] is False
