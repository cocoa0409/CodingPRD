"""Dealer account creation rules and system-wide authentication/lookup checks."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, NON_EXISTENT_UUID,
    assert_contractor, create_contractor_payload,
    TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["distributor_admin_headers"]


def test_contractor_create_defaults(api, admin_headers):
    """PRD §3.1: "The dealer's `tier` is not negotiable input: any value supplied at creation is ignored, and the account begins at `STANDARD` with `ytd_purchase_cents` at zero, both co-op accrual balances at zero, `training_credit_balance_hours` at zero, `compliance_standing` at `GOOD`, and `heel_violation_count_12m` at zero."
    PRD §3.1: "The creation payload may also carry `credit_hold` (defaulting to false) and a `status` of `ACTIVE` or `SUSPENDED` (defaulting to `ACTIVE`)."

    Design: Corner/entities/contractor_create_required_fields_and_defaults
    """
    res = api.create_contractor(
        {"company_name": "Fresh Air Co", "license_number": "LIC-C100"}, admin_headers)
    contractor = validate_success(res, 201)
    assert_contractor(contractor)
    assert contractor["tier"] == "STANDARD"
    assert contractor["ytd_purchase_cents"] == 0
    assert contractor["coop_accrual_provisional_cents"] == 0
    assert contractor["coop_accrual_final_cents"] == 0
    assert contractor["training_credit_balance_hours"] == 0
    assert contractor["compliance_standing"] == "GOOD"
    assert contractor["heel_violation_count_12m"] == 0
    assert contractor["credit_hold"] is False
    assert contractor["status"] == "ACTIVE"


def test_contractor_create_missing_license_rejected(api, admin_headers):
    """PRD §3.1: "A `DistributorAdmin` onboards a dealer by creating a `Contractor` with a `company_name` and a `license_number` — the state HVAC license, unique across all contractors, so a duplicate submission is rejected with `ERR_DUPLICATE` (409)."
    PRD §2.8: "22. **Structural payload validity** — required fields present and well-typed, unknown fields rejected; failures yield `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/contractor_create_missing_license_returns_invalid_request
    """
    res = api.create_contractor({"company_name": "No License LLC"}, admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_contractor_duplicate_license_rejected(api, admin_headers):
    """PRD §3.1: "A `DistributorAdmin` onboards a dealer by creating a `Contractor` with a `company_name` and a `license_number` — the state HVAC license, unique across all contractors, so a duplicate submission is rejected with `ERR_DUPLICATE` (409)."

    Design: Corner/entities/contractor_duplicate_license_rejected
    """
    first = api.create_contractor(
        {"company_name": "First", "license_number": "LIC-DUP"}, admin_headers)
    validate_success(first, 201)
    res = api.create_contractor(
        {"company_name": "Second", "license_number": "LIC-DUP"}, admin_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE)


def test_get_nonexistent_contractor_returns_not_found(api, admin_headers):
    """PRD §2.8: "3. **Path existence** — path identifiers are resolved strictly left to right; the first non-existent identifier yields `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/entity_get_not_found_returns_404
    """
    res = api.get_contractor(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_contractor_computed_fields_ignored_on_create(api, admin_headers):
    """PRD §3.1: "The dealer's `tier` is not negotiable input: any value supplied at creation is ignored, and the account begins at `STANDARD` with `ytd_purchase_cents` at zero, both co-op accrual balances at zero, `training_credit_balance_hours` at zero, `compliance_standing` at `GOOD`, and `heel_violation_count_12m` at zero."
    PRD §2.9: "Many fields in this system are **server-derived**; where a request supplies a value for a derived field, the supplied value is ignored."

    Design: Corner/entities/computed_field_input_ignored_on_create
    """
    res = api.create_contractor(
        {"company_name": "Sneaky Inc", "license_number": "LIC-C101",
         "tier": "PLATINUM", "ytd_purchase_cents": 999999999},
        admin_headers)
    contractor = validate_success(res, 201)
    assert contractor["tier"] == "STANDARD"
    assert contractor["ytd_purchase_cents"] == 0


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request whose headers are missing, or whose declared role is not one of these five values, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/roles/missing_auth_headers_rejected
    """
    res = api.list_contractors(headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
