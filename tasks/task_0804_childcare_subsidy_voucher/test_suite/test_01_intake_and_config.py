"""Household intake and configuration reference data (PRD §3.1, §3.2, §3.3, §2.9).

Corner-design coverage for entity creation, defaults, system fields, not-found,
and malformed-body handling.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    create_family_payload, create_provider_payload, create_income_standard_payload,
    assert_family, assert_provider, assert_income_standard,
    TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]
PA = TEST_USERS["program_admin_headers"]


def test_family_create_returns_pending_with_zero_ledger(api):
    """PRD §3.1: "Every new household starts with `status` equal to `PENDING`, an
    `active_authorization_id` of null, and a `total_copay_charged_cents` ledger of 0."

    Design: Corner/entities/family_create_returns_201_with_fields
    """
    resp = api.create_family(create_family_payload(
        applicant_name="New Fam", household_size=4, monthly_gross_income_cents=300_000,
        monthly_self_employment_income_cents=0, state_code="CA"), CW)
    data = validate_success(resp, expected_status=201)
    assert_family(data)
    assert data["status"] == "PENDING"
    assert data["household_size"] == 4
    assert data["total_copay_charged_cents"] == 0
    assert data["active_authorization_id"] is None


def test_family_get_unknown_id_returns_not_found(api):
    """PRD §2.9: "These are validated left to right, and the first identifier that
    fails to resolve causes immediate rejection with `ERR_NOT_FOUND`."

    Design: Corner/entities/family_get_not_found_returns_404
    """
    resp = api.get_family(NON_EXISTENT_UUID, CW)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_family_create_missing_applicant_name_rejected(api):
    """PRD §2.9: "A malformed body — a missing required field, a value of the wrong
    type, or an invalid enum value — is rejected with `ERR_VALIDATION`."

    Design: Corner/entities/family_create_missing_required_returns_invalid_request
    """
    resp = api.create_family({
        "household_size": 3,
        "monthly_gross_income_cents": 250_000,
        "state_code": "CA",
    }, CW)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_family_self_employment_income_defaults_to_zero(api):
    """PRD §3.1: "An optional `monthly_self_employment_income_cents` may be supplied;
    when omitted it defaults to 0."

    Design: Corner/entities/family_self_employment_income_defaults_zero
    """
    resp = api.create_family({
        "applicant_name": "Def Fam",
        "household_size": 3,
        "monthly_gross_income_cents": 250_000,
        "state_code": "CA",
    }, CW)
    data = validate_success(resp, expected_status=201)
    assert data["monthly_self_employment_income_cents"] == 0


def test_provider_create_starts_pending_verification_zero_ledger(api):
    """PRD §3.3: "A newly registered provider starts with `license_status`
    `PENDING_VERIFICATION` and a `total_net_paid_cents` ledger of 0."

    Design: Corner/entities/provider_create_starts_pending_verification
    """
    resp = api.create_provider(create_provider_payload(
        name="P One", provider_type="FAMILY_HOME", published_daily_rate_cents=4_000,
        license_expiry_date="2027-01-01T00:00:00Z", state_code="CA"), PA)
    data = validate_success(resp, expected_status=201)
    assert_provider(data)
    assert data["license_status"] == "PENDING_VERIFICATION"
    assert data["total_net_paid_cents"] == 0


def test_income_standard_create_returns_201_with_limits(api):
    """PRD §4: "Operations that create a new stand-alone resource return `201 Created`."
    PRD §3.2: "the `entry_monthly_limit_cents`, an initial-eligibility ceiling, and the
    `exit_monthly_limit_cents`, a more generous continuity-of-care ceiling used at
    redetermination that must be greater than or equal to the entry limit."

    Design: Corner/entities/income_standard_create_returns_201
    """
    resp = api.create_income_standard(create_income_standard_payload(
        household_size=2, entry_monthly_limit_cents=350_000,
        exit_monthly_limit_cents=450_000, state_code="CA"), PA)
    data = validate_success(resp, expected_status=201)
    assert_income_standard(data)
    assert data["entry_monthly_limit_cents"] == 350_000
