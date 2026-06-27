"""Account registration, config catalog, and structural-validation corners.

Queue B (Corner) — section: entities.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, ApiClient, ApiErrorId,
    assert_account,
    register_account_payload, create_model_portfolio_payload,
    create_subscription_plan_payload, create_linked_card_payload,
    TEST_USERS, make_investor_headers,
    create_plan, create_portfolio, create_verified_account, register_account,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_register_account_returns_201_with_defaults(api: ApiClient):
    """PRD §3.2: "A freshly registered account starts with `kyc_status` of
    `PENDING_KYC`, `billing_status` of `TRIAL`, and `cash_balance_cents` of zero."
    PRD §3.2: "The `sweep_threshold_cents` ... when omitted, defaults to 500 cents."

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    plan = create_plan(tier="LITE", monthly_fee_cents=300,
                       allows_custodial=False, allows_ira=False)
    portfolio = create_portfolio(target_allocation={"EQUITY": 40, "BOND": 60})
    res = api.register_account(
        register_account_payload(plan["id"], portfolio["id"], email="new-reg@x.com"), ANON
    )
    data = validate_success(res, expected_status=201)
    assert_account(data)
    assert data["kyc_status"] == "PENDING_KYC"
    assert data["billing_status"] == "TRIAL"
    assert data["cash_balance_cents"] == 0
    assert data["version"] == 1
    assert data["sweep_threshold_cents"] == 500


def test_get_account_not_found_returns_404(api: ApiClient):
    """PRD §3.12: "the read-by-id endpoints validate the path identifier
    left-to-right and return `ERR_NOT_FOUND` for an id that does not resolve."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    res = api.get_account("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_register_missing_plan_id_returns_invalid_request(api: ApiClient):
    """PRD §2.9: "fifth, structural validity of the body — required fields
    present, correctly typed, and enums within their domain
    (`ERR_INVALID_REQUEST`); sixth, pagination bounds on list endpoints
    (`ERR_INVALID_PAGINATION`); seventh, that the target resource is in a legal
    state for the requested transition (`ERR_INVALID_STATE`)."

    Design: Corner/entities/register_missing_plan_id_returns_invalid_request
    """
    portfolio = create_portfolio(target_allocation={"BOND": 100}, drift_band_bps=300)
    payload = {"email": "noplan@x.com", "full_name": "No Plan",
               "model_portfolio_id": portfolio["id"]}
    res = api.register_account(payload, ANON)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_account_computed_fields_input_ignored(api: ApiClient):
    """PRD §3.2: "A freshly registered account starts with `kyc_status` of
    `PENDING_KYC`, `billing_status` of `TRIAL`, and `cash_balance_cents` of zero."

    Design: Corner/entities/account_computed_fields_input_ignored
    """
    plan = create_plan()
    portfolio = create_portfolio()
    payload = register_account_payload(plan["id"], portfolio["id"], email="sysfld@x.com")
    payload["kyc_status"] = "VERIFIED"
    payload["cash_balance_cents"] = 99999
    res = api.register_account(payload, ANON)
    data = validate_success(res, expected_status=201)
    assert data["kyc_status"] == "PENDING_KYC", "client-supplied VERIFIED must be ignored"
    assert data["cash_balance_cents"] == 0, "client-supplied cash must be ignored"


def test_model_portfolio_allocation_sum_not_100_rejected(api: ApiClient):
    """PRD §3.1: "those weights must sum to exactly 100; any other sum is
    rejected with `ERR_ALLOCATION_SUM`."

    Design: Corner/entities/model_portfolio_allocation_sum_not_100_rejected
    """
    payload = create_model_portfolio_payload(
        risk_tier=4, name="Bad", target_allocation={"EQUITY": 50, "BOND": 40}
    )
    res = api.create_model_portfolio(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_ALLOCATION_SUM.value)


def test_linked_card_invalid_multiplier_rejected(api: ApiClient):
    """PRD §3.4: "The multiplier must be one of 1, 2, 3, or 10; supplying any
    other value is rejected with `ERR_INVALID_MULTIPLIER`, and when omitted the
    multiplier defaults to 1."

    Design: Corner/entities/linked_card_invalid_multiplier_rejected
    """
    acct, _, _ = create_verified_account()
    res = api.create_linked_card(
        create_linked_card_payload(acct["id"], last_four="9999", roundup_multiplier=5),
        make_investor_headers(acct["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_MULTIPLIER.value)


def test_list_accounts_pagination_invalid_limit_rejected(api: ApiClient):
    """PRD §2.3: "A request whose `limit` falls outside the inclusive range from 1
    to 100, or whose `offset` is below 0, is rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/entities/list_accounts_pagination_invalid_limit_rejected
    """
    res = api.list_accounts(ADMIN, params={"limit": 0})
    validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION.value)
