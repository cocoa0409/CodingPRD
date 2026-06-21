"""Account registration, KYC tier progression, RBAC, and authentication.

Each test translates exactly one design-index instance, named in the final
docstring tag of every test function.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    TEST_USERS, make_trader_headers, make_operator_headers, make_compliance_headers,
    make_headers, assert_account, ApiErrorId,
    create_account_payload, kyc_application_payload, kyc_decision_payload,
    btc_asset_payload, usd_asset_payload, tier_base_fee_schedule_payload,
    create_account, create_account_at_tier, set_clock, create_usd_btc_with_fees,
    create_btc_asset, credit_fiat, get_account_version,
)

OP = TEST_USERS["operator_headers"]


# ===========================================================================
# Corner / entities — Account creation, defaults, not-found, computed
# ===========================================================================
def test_account_create_returns_201_with_defaults(api):
    """PRD §3.1: "A newly created account starts at `kyc_tier` of `TIER_0`,
    `kyc_status` of `UNVERIFIED`, `account_status` of `ACTIVE`, and `version` of 1."
    PRD §3.1: "this is either `FIFO` or `HIFO`, defaults to `FIFO` when omitted"

    Design: Corner/entities/account_create_returns_201_with_defaults
    """
    resp = api.create_account(create_account_payload(email="new@x.com",
                                                      full_name="New User",
                                                      residence_country="US"))
    data = validate_success(resp, expected_status=201)
    assert data["kyc_tier"] == "TIER_0"
    assert data["kyc_status"] == "UNVERIFIED"
    assert data["account_status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["cost_basis_method"] == "FIFO"
    assert_account(data)


def test_account_missing_email_rejected(api):
    """PRD §2.10: "A malformed request body — a missing required field, an invalid
    enum value, or a negative number where one is forbidden — is rejected with
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "The registrant supplies an `email` (unique across all accounts), a
    `full_name`, and a `residence_country`"

    Design: Corner/entities/account_missing_required_field_rejected
    """
    resp = api.create_account({"full_name": "No Email", "residence_country": "US"})
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_account_default_cost_basis_method_fifo(api):
    """PRD §3.1: "The registrant may also choose a cost-basis policy by supplying
    `cost_basis_method`; this is either `FIFO` or `HIFO`, defaults to `FIFO` when
    omitted, is fixed at creation, and is immutable thereafter."

    Design: Corner/entities/account_default_cost_basis_method_applied
    """
    resp = api.create_account(create_account_payload(email="dflt@x.com",
                                                      full_name="Default CB",
                                                      residence_country="GB"))
    data = validate_success(resp, expected_status=201)
    assert data["cost_basis_method"] == "FIFO"


def test_account_not_found_returns_404(api):
    """PRD §2.9: "the system validates each referenced resource left to right and
    rejects the first identifier that does not resolve to an existing resource with
    `ERR_NOT_FOUND`."

    Design: Corner/entities/account_not_found_returns_404
    """
    resp = api.get_account("00000000-0000-4000-8000-000000000000", OP)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_account_computed_fee_tier_and_volume_ignore_input(api):
    """PRD §3.9: "the `taker_volume_30d_usd` field is the analogous sum where the
    account was the aggressing taker side, and it is this taker figure that drives
    the fee tier."
    PRD §3.9: "The resulting `fee_tier` — one of `TIER_BASE`, `TIER_1`, `TIER_2`, or
    `TIER_3` — is the schedule tier whose `min_taker_volume_30d_usd` is the highest
    inclusive lower bound at or below the account's taker volume."

    Design: Corner/entities/account_computed_fee_tier_ignores_input
    """
    api.create_fee_schedule(tier_base_fee_schedule_payload(), OP)
    acc = create_account(email="comp@x.com", full_name="Comp")
    data = validate_success(api.get_account(acc["id"], OP))
    assert data["taker_volume_30d_usd"] == 0
    assert data["fee_tier"] == "TIER_BASE"


# ===========================================================================
# Corner / validations — KYC tier progression
# ===========================================================================
def test_tier_progression_skip_rejected(api):
    """PRD §3.1: "when the requested tier is exactly one tier above the current
    `kyc_tier` — skipping a tier, or applying while a review is already `PENDING`, is
    rejected with `ERR_INVALID_TIER_PROGRESSION`."

    Design: Corner/validations/tier_progression_skip_rejected
    """
    acc = create_account(email="tp@x.com", full_name="TP")
    trader = make_trader_headers(acc["id"])
    resp = api.create_kyc_application(acc["id"], kyc_application_payload("TIER_2"), trader)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIER_PROGRESSION.value)


# ===========================================================================
# Corner / state_machines — KYC decision on non-PENDING account
# ===========================================================================
def test_kyc_decision_on_non_pending_returns_invalid_state(api):
    """PRD §3.1: "An `Operator` resolves a pending application with a `decision` of
    either `APPROVE` or `REJECT`, an operation defined only while `kyc_status` is
    `PENDING`."

    Design: Corner/state_machines/kyc_decision_on_non_pending_returns_invalid_state
    """
    acc = create_account(email="kd@x.com", full_name="KD")
    resp = api.create_kyc_decision(acc["id"], kyc_decision_payload("APPROVE"), OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / rbac — role and ownership denials, authentication
# ===========================================================================
def test_trader_cannot_create_asset(api):
    """PRD §2.1: "A request whose role is recognized and authenticated but not
    permitted to perform the targeted operation under the access matrix in Section 4
    is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: "POST | `/assets` | Create an asset configuration | Operator"

    Design: Corner/rbac/trader_cannot_create_asset
    """
    acc = create_account(email="rb1@x.com", full_name="RB1")
    trader = make_trader_headers(acc["id"])
    resp = api.create_asset(
        {"symbol": "DOGE", "decimals": 8, "required_confirmations": 6,
         "is_fiat": False, "min_withdrawal_amount": 1, "network_fee": 1,
         "spot_price_usd": 0.1},
        trader,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_operator_cannot_screen_withdrawal(api):
    """PRD §2.1: "A request whose role is recognized and authenticated but not
    permitted to perform the targeted operation under the access matrix in Section 4
    is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: "POST | `/withdrawals/{id}/screen` | Begin compliance screening |
    ComplianceOfficer"

    Design: Corner/rbac/operator_cannot_screen_withdrawal
    """
    set_clock("2028-01-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_1", email="rb2@x.com", full_name="RB2")
    acc_id = acc["id"]
    trader = make_trader_headers(acc_id)
    # credit BTC, add+activate address, submit a SUBMITTED withdrawal
    dep = validate_success(api.create_deposit(
        {"account_id": acc_id, "asset": "BTC", "amount": 1.0, "unit_cost_usd": 30000},
        OP), 201)
    # Non-fiat deposits pass through CONFIRMING (PRD §3.4): the first advance
    # enters CONFIRMING (held); a subsequent advance reaching required credits
    # the funds to available so the withdrawal below is funded.
    api.advance_confirmations(dep["id"], {"delta": 1}, OP)
    api.advance_confirmations(dep["id"], {"delta": 1}, OP)
    version = get_account_version(acc_id, trader)
    addr = validate_success(api.create_withdrawal_address(
        {"account_id": acc_id, "asset": "BTC", "chain_address": "0xRB2",
         "label": "out", "expected_account_version": version}, trader), 201)
    set_clock("2028-01-02T01:00:00Z")
    api.activate_withdrawal_address(addr["id"], trader)
    wd = validate_success(api.create_withdrawal(
        {"account_id": acc_id, "withdrawal_address_id": addr["id"], "amount": 0.01},
        trader), 201)
    resp = api.screen_withdrawal(wd["id"], OP)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_trader_cannot_act_on_other_account_order(api):
    """PRD §2.1: "A `Trader` acting on a resource whose `account_id` does not equal
    their `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/trader_cannot_act_on_other_account_order
    """
    create_usd_btc_with_fees()
    acc_a = create_account(email="owA@x.com", full_name="OwA")
    acc_b = create_account_at_tier("TIER_1", email="owB@x.com", full_name="OwB")
    b_id = acc_b["id"]
    trader_b = make_trader_headers(b_id)
    credit_fiat(b_id, "USD", 50000)
    version = get_account_version(b_id, trader_b)
    order = validate_success(api.create_order(
        {"account_id": b_id, "base_asset": "BTC", "quote_asset": "USD",
         "side": "BUY", "order_type": "LIMIT", "quantity": 1.0, "limit_price": 40000,
         "time_in_force": "GTC", "expected_account_version": version}, trader_b), 201)
    # account A tries to cancel B's order
    trader_a = make_trader_headers(acc_a["id"])
    resp = api.cancel_order(order["id"], trader_a)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request that omits either header, or that presents an
    `X-User-Role` value that is not one of these recognized roles, is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    resp = api.list_orders(make_headers("Nobody", "someone"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
