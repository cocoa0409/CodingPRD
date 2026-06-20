"""Validation violations mapping to their canonical errors.

Corner queue B: section validations (non-stub instances only; the payoff-sum
boundary is owned by a §1.8 difficulty instance).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_borrower_headers,
    make_servicing_agent_headers,
    make_underwriter_headers,
    setup_prequalified_application,
    setup_locked_application,
    setup_approved_application,
    setup_funded_loan,
    create_borrower,
    create_application,
    invite_cosigner,
    consent_cosigner,
    start_forbearance,
    api_client,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BORROWER = TEST_USERS["borrower_headers"]


def test_duplicate_borrower_email_rejected(api):
    """PRD 3.1: "The email must be non-empty and unique across borrowers; a
    duplicate is rejected with ERR_DUPLICATE_KEY."

    Design: Corner/validations/duplicate_borrower_email_rejected
    """
    get_success_data(api.create_borrower(
        {"email": "dup@x.com", "full_name": "First", "annual_income_cents": 5_000_000,
         "fico_band": "PRIME"}, BORROWER))
    resp = api.create_borrower(
        {"email": "dup@x.com", "full_name": "Second", "annual_income_cents": 6_000_000,
         "fico_band": "PRIME"}, BORROWER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value, 409)


def test_duplicate_pool_code_rejected(api):
    """PRD 3.1: "An ABS pool is created with a pool_code (non-empty and unique; a
    collision is rejected with ERR_DUPLICATE_KEY)"

    Design: Corner/validations/duplicate_pool_code_rejected
    """
    get_success_data(api.create_abs_pool(
        {"pool_code": "DUP-POOL", "max_principal_cents": 10_000_000, "min_fico_band": "SUBPRIME",
         "allowed_rate_type": "ANY"}, ADMIN))
    resp = api.create_abs_pool(
        {"pool_code": "DUP-POOL", "max_principal_cents": 20_000_000, "min_fico_band": "PRIME",
         "allowed_rate_type": "FIXED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KEY.value, 409)


def test_second_cosigner_invite_rejected(api):
    """PRD 3.3: "Inviting a second cosigner to an application that already has one
    is rejected with ERR_COSIGNER_ALREADY_ATTACHED (HTTP 409)."

    Design: Corner/validations/second_cosigner_invite_rejected
    """
    borrower = create_borrower(email="corner.b23@x.com", full_name="Corner B23",
                               annual_income_cents=5_000_000, fico_band="PRIME")
    application = create_application(borrower, requested_principal_cents=4_000_000,
                                     requested_term_months=60, requested_rate_type="FIXED")
    invite_cosigner(borrower, application, cosigner_email="first.c@x.com",
                    cosigner_annual_income_cents=2_000_000)
    resp = api.create_cosigner(
        {"application_id": application["id"], "cosigner_email": "second.c@x.com",
         "cosigner_annual_income_cents": 3_000_000}, make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_COSIGNER_ALREADY_ATTACHED.value, 409)


def test_prequalify_no_matching_rate_rejected(api):
    """PRD 3.2: "If no row matches, prequalification is rejected with
    ERR_NO_MATCHING_RATE (HTTP 422) and no offers are created."

    Application is FIXED 240-month but the only grid cell is FIXED 60-month.

    Design: Corner/validations/prequalify_no_matching_rate_rejected
    """
    from test_helpers import create_rate_grid_entry
    create_rate_grid_entry(rate_type="FIXED", term_months=60, min_fico_band="NEAR_PRIME",
                           base_apr_bps=650, index_apr_bps=0)
    borrower = create_borrower(email="corner.b24@x.com", full_name="Corner B24",
                               annual_income_cents=30_000_000, fico_band="PRIME")
    application = create_application(borrower, requested_principal_cents=5_000_000,
                                     requested_term_months=240, requested_rate_type="FIXED")
    resp = api.prequalify_application(application["id"], make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_MATCHING_RATE.value, 422)
    app_after = get_success_data(api.get_application(application["id"], make_borrower_headers(borrower["id"])))
    assert app_after["status"] == "DRAFT", f"status must stay DRAFT, got {app_after['status']}"


def test_approve_already_approved_returns_invalid_state(api):
    """PRD 3.5: "Approval is defined only from UNDER_REVIEW; from any other state
    ERR_INVALID_STATE applies."

    Re-approving an already-APPROVED application hits the state precondition,
    which §2.6 pins to fire before the locked-offer business check.

    Design: Corner/validations/approve_zero_locked_offers_rejected
    """
    bundle = setup_approved_application(
        autopay_elected=False,
        underwriter_id="uw-corner-10",
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    resp = api.approve_application(bundle["application"]["id"], make_underwriter_headers("uw-corner-10"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_forbearance_term_zero_rejected(api):
    """PRD 3.11: "a months_requested that must be between 1 and 12 inclusive; a
    value outside that range is rejected with ERR_FORBEARANCE_TERM_INVALID (HTTP
    422)."

    Design: Corner/validations/forbearance_term_zero_rejected
    """
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-FBT", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    resp = api.start_forbearance(bundle["loan"]["id"], {"reason_code": "OTHER", "months_requested": 0},
                                 make_servicing_agent_headers("sa-corner-11"))
    validate_error(resp, ApiErrorId.ERR_FORBEARANCE_TERM_INVALID.value, 422)


def test_forbearance_on_forbearance_loan_returns_invalid_state(api):
    """PRD 3.11: "Placing a loan into hardship forbearance is defined only when the
    loan's repayment_status is CURRENT and only when no ACTIVE forbearance plan
    already exists for the loan."

    A loan already in FORBEARANCE hits the state precondition (§2.6 pins state
    before the ACTIVE-plan business check) -> ERR_INVALID_STATE.

    Design: Corner/validations/forbearance_already_active_rejected
    """
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-FBA", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
    )
    loan = bundle["loan"]
    start_forbearance(loan, servicing_agent_id="sa-corner-12", reason_code="MEDICAL", months_requested=3)
    resp = api.start_forbearance(loan["id"], {"reason_code": "MEDICAL", "months_requested": 2},
                                 make_servicing_agent_headers("sa-corner-12"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_release_not_eligible_rejected(api):
    """PRD 3.10: "Release is defined only when the cosigner's consent_status is
    CONSENTED and only when the funded loan's cosigner_release_status is ELIGIBLE;
    a release attempted while the loan is not eligible is rejected with
    ERR_RELEASE_NOT_ELIGIBLE (HTTP 409)."

    A funded loan with a CONSENTED cosigner but release status PENDING (no streak)
    cannot be released.

    Design: Corner/validations/release_not_eligible_rejected
    """
    bundle = setup_funded_loan(
        autopay_elected=False,
        pool_overrides={"pool_code": "CORNER-POOL-REL", "max_principal_cents": 20_000_000,
                        "min_fico_band": "SUBPRIME", "allowed_rate_type": "ANY"},
        grid_overrides={"rate_type": "FIXED", "term_months": 120, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 30_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 5_000_000,
                               "requested_term_months": 120, "requested_rate_type": "FIXED"},
        with_cosigner=True,
        cosigner_overrides={"cosigner_annual_income_cents": 6_000_000},
    )
    cosigner = bundle["cosigner"]
    borrower = bundle["borrower"]
    resp = api.release_cosigner(cosigner["id"], make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_RELEASE_NOT_ELIGIBLE.value, 409)
    from test_helpers import get_loan
    assert get_loan(bundle["loan"]["id"])["cosigner_release_status"] == "PENDING"


def test_dti_exceeded_on_approve_rejected(api):
    """PRD 3.5: "then the application's dti_ratio must be at most the maximum
    allowed ratio of 0.4300, and a ratio strictly above that limit is rejected
    with ERR_DTI_EXCEEDED (HTTP 422)."

    principal 10,000,000 at 60mo on income 4,000,000 -> dti 0.5640 > 0.4300.

    Design: Corner/validations/dti_exceeded_on_approve_rejected
    """
    bundle = setup_locked_application(
        autopay_elected=False,
        grid_overrides={"rate_type": "FIXED", "term_months": 60, "min_fico_band": "NEAR_PRIME",
                        "base_apr_bps": 650, "index_apr_bps": 0},
        borrower_overrides={"annual_income_cents": 4_000_000, "fico_band": "PRIME"},
        application_overrides={"requested_principal_cents": 10_000_000,
                               "requested_term_months": 60, "requested_rate_type": "FIXED"},
    )
    assert bundle["application"]["dti_ratio"] == pytest.approx(0.5640, abs=1e-9)
    resp = api.approve_application(bundle["application"]["id"], make_underwriter_headers("uw-corner-14"))
    validate_error(resp, ApiErrorId.ERR_DTI_EXCEEDED.value, 422)


def test_pagination_limit_too_large_rejected(api):
    """PRD 2.3: "A limit below 1 or above 100, or a negative offset, is rejected
    with ERR_PAGINATION_INVALID (HTTP 400)."

    Design: Corner/validations/pagination_limit_too_large_rejected
    """
    resp = api.list_applications(make_underwriter_headers("uw-corner-15"), params={"limit": 101, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value, 400)


def test_pagination_negative_offset_rejected(api):
    """PRD 2.3: "A limit below 1 or above 100, or a negative offset, is rejected
    with ERR_PAGINATION_INVALID (HTTP 400)."

    Design: Corner/validations/pagination_negative_offset_rejected
    """
    resp = api.list_offers(make_borrower_headers("00000000-0000-4000-8000-0000000000cc"),
                           params={"offset": -1})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value, 400)
