"""Disclosure supersession, list/reverse-reachability reads, basic CRUD validation,
not-found integrity, and RBAC denials.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_borrower, create_funding_loan, create_application,
    file_disclosure, create_investor, fund_loan_fully,
    NON_EXISTENT_UUID,
    ADMIN, CO,
    make_borrower_headers, make_investor_headers,
)


# =====================================================================
# Rule 8b — temporal/single-occupancy: latest FILED prospectus supersedes prior
# =====================================================================

def test_filing_second_prospectus_supersedes_prior(api):
    """PRD §3.8: "When a new disclosure is filed for a loan, any prior `FILED`
    disclosure of the same `loan_id` and the same `document_type` is automatically
    marked `SUPERSEDED`, so that only the most recently filed prospectus is the one
    consulted at disbursement time."

    Design: Difficulty/resource_temporal_overlap/disclosure_supersession_latest_filed_wins_per_type
    """
    borrower, app, loan = create_funding_loan()
    disc1 = file_disclosure(loan["id"], "SERIES_NOTE_PROSPECTUS", officer_id="co_1")
    disc2 = file_disclosure(loan["id"], "SERIES_NOTE_PROSPECTUS", officer_id="co_2")
    after1 = validate_success(api.get_disclosure(disc1["id"], CO), 200)
    after2 = validate_success(api.get_disclosure(disc2["id"], CO), 200)
    assert after1["status"] == "SUPERSEDED", "prior prospectus must be superseded"
    assert after2["status"] == "FILED", "latest prospectus stays FILED"


def test_only_one_filed_prospectus_remains_after_supersession(api):
    """PRD §3.8: "Disclosures supersede one another within a category."
    PRD §2.9: "These reverse-reachability reads return the matching child resources
    sorted by creation time ascending, consistent with §2.3."

    Design: Difficulty/resource_temporal_overlap/disclosure_supersession_latest_filed_wins_per_type
    """
    borrower, app, loan = create_funding_loan()
    file_disclosure(loan["id"], "SERIES_NOTE_PROSPECTUS", officer_id="co_1")
    file_disclosure(loan["id"], "SERIES_NOTE_PROSPECTUS", officer_id="co_2")
    resp = api.list_loan_disclosures(
        loan["id"], CO,
        params={"document_type": "SERIES_NOTE_PROSPECTUS", "status": "FILED"},
    )
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"exactly one FILED prospectus should remain, got {len(data)}"
    assert data[0]["status"] == "FILED"


# =====================================================================
# Corner — endpoints: listing + reverse-reachability
# =====================================================================

def test_list_loans_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope, where `total_count`
    reflects the full count of matching resources before pagination and `has_more`
    indicates whether further pages remain."

    Design: Corner/endpoints/list_loans_pagination_envelope
    """
    create_funding_loan()  # at least one originated loan
    resp = api.list_loans(ADMIN, params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


def test_list_investments_for_loan_reverse_reachability(api):
    """PRD §2.9: "the investments funding a given loan ... These reverse-reachability
    reads return the matching child resources sorted by creation time ascending"

    Design: Corner/endpoints/filtered_list_investments_by_loan_reverse_reachability
    """
    borrower, app, loan = create_funding_loan()
    i1 = create_investor()
    i2 = create_investor()
    fund_loan_fully(loan, [(i1, 800_000), (i2, 400_000)])
    resp = api.list_loan_investments(loan["id"], ADMIN)
    data, _meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 investments funding the loan, got {len(data)}"
    assert sum(inv["amount_cents"] for inv in data) == 1_200_000


# =====================================================================
# Corner — entities/errors: creation, not-found, validation
# =====================================================================

def test_create_borrower_returns_201_active(api):
    """PRD §3.1: "A newly registered borrower begins in `ACTIVE` status."

    Design: Corner/entities/create_borrower_returns_201_with_active_status
    """
    resp = api.create_borrower(
        {"business_name": "New Biz", "ein": "10-1000001", "state_code": "CA"}, ADMIN
    )
    data = validate_success(resp, 201)
    assert data["status"] == "ACTIVE"
    assert data["business_name"] == "New Biz"


def test_get_borrower_not_found(api):
    """PRD §2.7: "Existence comes third: every identifier supplied in the path or
    body must resolve to an existing resource, and these are checked left-to-right,
    with the first unresolved identifier producing `ERR_NOT_FOUND`."

    Design: Corner/entities/get_borrower_not_found_returns_404
    """
    resp = api.get_borrower(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_application_missing_required_field(api):
    """PRD §2.7: "any request that is missing a required field, supplies a value of
    the wrong type, or supplies a value outside its declared constraints is rejected
    with `ERR_VALIDATION`."

    Design: Corner/entities/create_loan_application_missing_required_field_returns_validation
    """
    borrower = create_borrower()
    resp = api.create_loan_application(
        {"borrower_id": borrower["id"], "term_months": 12,
         "plaid_avg_monthly_revenue_cents": 3_000_000,
         "plaid_monthly_debt_payment_cents": 1_000_000,
         "plaid_nsf_count_90d": 0, "plaid_account_age_months": 48},
        make_borrower_headers(borrower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_application_invalid_term_months_validation(api):
    """PRD §3.1: "the term must be exactly one of 12, 24, 36, or 60 months."
    PRD §2.7: "supplies a value outside its declared constraints is rejected with
    `ERR_VALIDATION`."

    Design: Corner/entities/loan_application_invalid_term_months_enum_returns_validation
    """
    borrower = create_borrower()
    resp = api.create_loan_application(
        {"borrower_id": borrower["id"], "requested_principal_cents": 1_200_000,
         "term_months": 18, "plaid_avg_monthly_revenue_cents": 3_000_000,
         "plaid_monthly_debt_payment_cents": 1_000_000,
         "plaid_nsf_count_90d": 0, "plaid_account_age_months": 48},
        make_borrower_headers(borrower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_requested_principal_below_minimum_validation(api):
    """PRD §3.1: "The requested principal must be at least 100000 cents and at most
    50000000 cents"

    Design: Corner/errors/requested_principal_below_minimum_returns_validation
    """
    borrower = create_borrower()
    resp = api.create_loan_application(
        {"borrower_id": borrower["id"], "requested_principal_cents": 50_000,
         "term_months": 12, "plaid_avg_monthly_revenue_cents": 3_000_000,
         "plaid_monthly_debt_payment_cents": 1_000_000,
         "plaid_nsf_count_90d": 0, "plaid_account_age_months": 48},
        make_borrower_headers(borrower["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 400)


def test_application_unknown_borrower_not_found(api):
    """PRD §2.7: "Existence comes third: every identifier supplied in the path or
    body must resolve to an existing resource ... with the first unresolved
    identifier producing `ERR_NOT_FOUND`."

    Design: Corner/entities/application_wrong_parent_borrower_not_found
    """
    resp = api.create_loan_application(
        {"borrower_id": NON_EXISTENT_UUID, "requested_principal_cents": 1_200_000,
         "term_months": 12, "plaid_avg_monthly_revenue_cents": 3_000_000,
         "plaid_monthly_debt_payment_cents": 1_000_000,
         "plaid_nsf_count_90d": 0, "plaid_account_age_months": 48},
        make_borrower_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_investment_unknown_loan_not_found(api):
    """PRD §2.7: "Existence comes third ... checked left-to-right, with the first
    unresolved identifier producing `ERR_NOT_FOUND`."
    PRD §2.6: "This rejection is evaluated before any fiscal-capacity check"

    Design: Corner/entities/flat_fk_integrity_investment_unknown_loan_not_found
    """
    # Build a real loan only to source a real version token.
    borrower, app, loan = create_funding_loan()
    real_v = loan["version"]
    inv = create_investor()
    resp = api.create_investment(
        {"investor_id": inv["id"], "loan_id": NON_EXISTENT_UUID, "amount_cents": 400_000,
         "expected_loan_version": real_v},
        make_investor_headers(inv["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# =====================================================================
# Corner — RBAC
# =====================================================================

def test_borrower_cannot_score_application_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted
    to invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/borrower_cannot_score_application_forbidden
    """
    borrower, app = create_application()
    resp = api.score_application(app["id"], make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_investor_cannot_file_disclosure_forbidden(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted
    to invoke the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/investor_cannot_file_compliance_disclosure_forbidden
    """
    borrower, app, loan = create_funding_loan()
    inv = create_investor(deposit_cents=0)
    resp = api.create_disclosure(
        {"loan_id": loan["id"], "document_type": "SERIES_NOTE_PROSPECTUS"},
        make_investor_headers(inv["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_missing_auth_headers_on_score_unauthenticated(api):
    """PRD §2.1: "With the sole exception of borrower self-registration and investor
    self-registration, a request missing either header is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_on_score_returns_unauthenticated
    """
    borrower, app = create_application()
    # No X-User-ID / X-User-Role headers at all.
    resp = api.score_application(app["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
