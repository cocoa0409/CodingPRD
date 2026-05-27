"""Entity CRUD: required fields, defaults, type constraints, not-found,
listing, parent FK validation."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, TEST_USERS, NON_EXISTENT_UUID,
    set_clock,
    create_claimant, create_application_for_claimant, post_work_credit,
    create_claimant_payload, create_application_payload,
    create_work_credit_payload,
)


# =========================================================================
# Instance: create_claimant_missing_full_name_returns_invalid_request
# =========================================================================

def test_create_claimant_missing_full_name_returns_invalid_request(api):
    """PRD §2.5: "Request bodies that are syntactically malformed — missing
    a required field, type mismatch, or carrying an unknown field — are
    rejected upstream of either of these checks with `ERR_INVALID_REQUEST`
    (400)."
    PRD §3.1: "A claim begins with a `Claimant` record. The intake payload
    carries the claimant's `ssn_last4` — exactly four digits matching the
    regular pattern of four decimal digits — alongside their `full_name`,
    their `date_of_birth` (an ISO 8601 instant used by every age-bucket
    rule that follows), and their `filing_state`"

    Design: Corner/entities/create_claimant_missing_full_name_returns_invalid_request
    """
    set_clock("2026-01-15T00:00:00Z")
    payload = {
        "ssn_last4": "0001",
        "date_of_birth": "1980-01-01T00:00:00Z",
        "filing_state": "TX",
    }
    res = api_client.create_claimant(payload, TEST_USERS["ssa_admin_headers"])
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# =========================================================================
# Instance: create_claimant_default_monthly_income_zero
# =========================================================================

def test_create_claimant_default_monthly_income_zero(api):
    """PRD §3.1: "Two optional fiscal inputs may also be captured at intake:
    `monthly_income_cents`, the claimant's countable monthly unearned
    income (defaulting to 0 cents if omitted), and `countable_resources_cents`,
    the dollar-equivalent of countable resources in cents (also defaulting
    to 0)."

    Design: Corner/entities/create_claimant_default_monthly_income_zero
    """
    set_clock("2026-01-15T00:00:00Z")
    c = create_claimant(
        ssn_last4="0002",
        full_name="Default Income",
        date_of_birth="1985-01-01T00:00:00Z",
        filing_state="TX",
    )
    assert c["monthly_income_cents"] == 0, \
        f"Expected default 0, got {c['monthly_income_cents']}"
    assert c["countable_resources_cents"] == 0


# =========================================================================
# Instance: create_application_default_claim_type_ssdi_only
# =========================================================================

def test_create_application_default_claim_type_ssdi_only(api):
    """PRD §3.2: "an optional `claim_type` of either `SSDI_ONLY` or
    `CONCURRENT_SSDI_SSI` (defaulting to `SSDI_ONLY`)."
    PRD §3.2: "The resource is created at `version` 1 with `status` of
    `DRAFT`"

    Design: Corner/entities/create_application_default_claim_type_ssdi_only
    """
    set_clock("2026-01-15T00:00:00Z")
    c = create_claimant(
        ssn_last4="0003",
        full_name="Def Claim",
        date_of_birth="1985-01-01T00:00:00Z",
        filing_state="TX",
    )
    # Create application with no claim_type field at all.
    payload = {
        "claimant_id": c["id"],
        "alleged_onset_date": "2024-01-01T00:00:00Z",
        "protective_filing_date": "2026-01-15T00:00:00Z",
    }
    res = api_client.create_application(payload, TEST_USERS["ssa_admin_headers"])
    app = get_success_data(res)
    assert app["claim_type"] == "SSDI_ONLY"
    assert app["status"] == "DRAFT"
    assert app["version"] == 1


# =========================================================================
# Instance: create_claimant_invalid_state_code_returns_422
# =========================================================================

def test_create_claimant_invalid_state_code_returns_422(api):
    """PRD §3.1: "their `filing_state` (a USPS two-letter uppercase state
    code, required to be in the recognised set; an unrecognised code is
    rejected with `ERR_INVALID_STATE_CODE`)."

    Design: Corner/entities/create_claimant_invalid_state_code_returns_422
    """
    set_clock("2026-01-15T00:00:00Z")
    payload = {
        "ssn_last4": "0004",
        "full_name": "Bad State",
        "date_of_birth": "1985-01-01T00:00:00Z",
        "filing_state": "XYZ",
    }
    res = api_client.create_claimant(payload, TEST_USERS["ssa_admin_headers"])
    validate_error(res, "ERR_INVALID_STATE_CODE", expected_status=422)


# =========================================================================
# Instance: get_claimant_not_found_returns_404
# =========================================================================

def test_get_claimant_not_found_returns_404(api):
    """PRD §2.5: "Identifiers in the path are validated strictly left to
    right: the first identifier in the path that does not resolve to an
    extant resource causes the request to be rejected with `ERR_NOT_FOUND`
    (404), before any deeper identifier is consulted."

    Design: Corner/entities/get_claimant_not_found_returns_404
    """
    set_clock("2026-01-15T00:00:00Z")
    res = api_client.get_claimant(NON_EXISTENT_UUID, TEST_USERS["ssa_admin_headers"])
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# =========================================================================
# Instance: list_claimants_pagination_meta_present
# =========================================================================

def test_list_claimants_pagination_meta_present(api):
    """PRD §2.3: "The four pagination fields `limit`, `offset`,
    `total_count`, and `has_more` are always populated inside the `meta`
    object of every list response."

    Design: Corner/entities/list_claimants_pagination_meta_present
    """
    set_clock("2026-01-15T00:00:00Z")
    create_claimant(ssn_last4="0005", full_name="Page A",
                    date_of_birth="1980-01-01T00:00:00Z", filing_state="TX")
    create_claimant(ssn_last4="0006", full_name="Page B",
                    date_of_birth="1980-01-01T00:00:00Z", filing_state="TX")
    res = api_client.list_claimants(TEST_USERS["ssa_admin_headers"],
                                    params={"limit": 1, "offset": 0})
    items, meta = validate_paginated(res)
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(items) == 1


# =========================================================================
# Instance: workcredit_duplicate_year_returns_409
# =========================================================================

def test_workcredit_duplicate_year_returns_409(api):
    """PRD §3.1: "Posting work credits is exclusive to `SSAAdmin`: each
    posted record produces a 201 Created, and an attempt to post a second
    record for a `(claimant_id, year)` pair that already exists is
    rejected with `ERR_DUPLICATE_CREDIT_YEAR` (409)."

    Design: Corner/entities/workcredit_duplicate_year_returns_409
    """
    set_clock("2026-01-15T00:00:00Z")
    c = create_claimant(ssn_last4="0007", full_name="Dup Year",
                        date_of_birth="1980-01-01T00:00:00Z", filing_state="TX")
    post_work_credit(c["id"], 2020, credits_earned=4, earnings_cents=4_800_000)
    # Second post with same (claimant_id, year).
    payload = create_work_credit_payload(c["id"], 2020, credits_earned=2,
                                          earnings_cents=2_000_000)
    res = api_client.create_work_credit(payload, TEST_USERS["ssa_admin_headers"])
    validate_error(res, "ERR_DUPLICATE_CREDIT_YEAR", expected_status=409)


# =========================================================================
# Instance: create_application_with_nonexistent_claimant_returns_reference_not_found
# =========================================================================

def test_create_application_with_nonexistent_claimant_returns_reference_not_found(api):
    """PRD §2.5: "any `claimant_id`, `application_id`, or
    `benefit_award_id` in a body must resolve to an existing resource,
    and a payload referencing a non-existent parent is rejected with
    `ERR_REFERENCE_NOT_FOUND` (404)."

    Design: Corner/entities/create_application_with_nonexistent_claimant_returns_reference_not_found
    """
    set_clock("2026-01-15T00:00:00Z")
    payload = create_application_payload(
        claimant_id=NON_EXISTENT_UUID,
        alleged_onset_date="2024-01-01T00:00:00Z",
        protective_filing_date="2026-01-15T00:00:00Z",
        claim_type="SSDI_ONLY",
    )
    res = api_client.create_application(payload, TEST_USERS["ssa_admin_headers"])
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", expected_status=404)
