"""Staking: reward accrual, the zero-reward claim boundary, the closed unbonding
cooldown overlap, and release-before-cooldown."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_trader_headers, find_balance, ApiErrorId,
    set_clock, create_eth_asset, create_account_at_tier, create_and_credit_deposit,
    setup_staking_position,
)

OP = TEST_USERS["operator_headers"]


def _eth_account_with_balance(clock, amount=100, email="stk@x.com", full_name="Stk"):
    set_clock(clock)
    create_eth_asset()
    acc = create_account_at_tier("TIER_1", email=email, full_name=full_name)
    create_and_credit_deposit(acc["id"], "ETH", amount, 1800, required_confirmations=1)
    return acc


# ===========================================================================
# Difficulty / boundary_precision_check — zero-reward claim boundary
# ===========================================================================
def test_claim_at_stake_instant_zero_rewards_rejected(api):
    """PRD §3.11: "claiming is permitted only when the resulting `accrued_rewards` is
    strictly greater than zero — a claim that would yield exactly zero after accrual
    is rejected with `ERR_NOTHING_TO_CLAIM`."

    Design: Difficulty/boundary_precision_check/staking_claim_zero_rewards_boundary
    """
    acc = _eth_account_with_balance("2026-11-01T00:00:00Z", email="stk1@x.com",
                                    full_name="Stk1")
    pos = setup_staking_position(acc["id"], "ETH", 100, 500)
    trader = make_trader_headers(acc["id"])
    # claim at the exact stake instant (elapsed 0 -> accrued 0)
    resp = api.claim_staking_position(pos["id"], trader)
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_CLAIM.value)


def test_claim_after_accrual_credits_rewards(api):
    """PRD §3.11: "A successful claim credits the accrued rewards into
    `available_amount`"
    PRD §3.11: "computes the reward increment as the `principal_amount` multiplied by
    the annual rate (`apr_bps` divided by ten thousand) multiplied by the elapsed
    seconds divided by the number of seconds in a year (31,536,000, that is 365 days)"

    Design: Difficulty/boundary_precision_check/staking_claim_zero_rewards_boundary
    """
    acc = _eth_account_with_balance("2027-08-01T00:00:00Z", email="stk2@x.com",
                                    full_name="Stk2")
    pos = setup_staking_position(acc["id"], "ETH", 100, 500)
    trader = make_trader_headers(acc["id"])
    # advance exactly half a year -> accrued 2.5 ETH (> 0), so the claim succeeds
    set_clock("2028-01-30T12:00:00Z")
    validate_success(api.claim_staking_position(pos["id"], trader))
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": acc["id"], "asset": "ETH"}))
    eth = find_balance(bals, "ETH")
    assert eth["available_amount"] == pytest.approx(2.5, abs=1e-6)


# ===========================================================================
# Corner / calculations — half-year reward correctness
# ===========================================================================
def test_staking_half_year_reward_correct(api):
    """PRD §3.11: "When rewards are brought current, the system measures the elapsed
    seconds from the position's `last_accrual_at` to the current clock, computes the
    reward increment as the `principal_amount` multiplied by the annual rate
    (`apr_bps` divided by ten thousand) multiplied by the elapsed seconds divided by
    the number of seconds in a year (31,536,000, that is 365 days)"

    Design: Corner/calculations/staking_half_year_reward_correct
    """
    acc = _eth_account_with_balance("2027-08-01T00:00:00Z", email="sh@x.com",
                                    full_name="SH")
    pos = setup_staking_position(acc["id"], "ETH", 100, 500)
    trader = make_trader_headers(acc["id"])
    # 2027-08-01 .. 2028-01-30T12:00 == 15768000s == 0.5y; 100*0.05*0.5 == 2.5
    set_clock("2028-01-30T12:00:00Z")
    validate_success(api.claim_staking_position(pos["id"], trader))
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": acc["id"], "asset": "ETH"}))
    eth = find_balance(bals, "ETH")
    assert eth["available_amount"] == pytest.approx(2.5, abs=1e-6)


# ===========================================================================
# Corner / state_machines — release before cooldown
# ===========================================================================
def test_release_before_cooldown_returns_nothing_to_claim(api):
    """PRD §3.11: "A `Trader` releases the principal after the cooldown, moving the
    position along `UNBONDING → CLOSED`; release is permitted only when the current
    clock is at or after `unbond_available_at`, and an attempt to release before that
    instant is rejected with `ERR_NOTHING_TO_CLAIM`."

    Design: Corner/state_machines/staking_release_before_cooldown_returns_nothing_to_claim
    """
    acc = _eth_account_with_balance("2027-07-01T00:00:00Z", email="sr@x.com",
                                    full_name="SR")
    pos = setup_staking_position(acc["id"], "ETH", 100, 500)
    trader = make_trader_headers(acc["id"])
    validate_success(api.unbond_staking_position(pos["id"], trader))
    # unbond_available_at is 2027-07-08; advance only to 2027-07-03 (before cooldown end)
    set_clock("2027-07-03T00:00:00Z")
    resp = api.release_staking_position(pos["id"], trader)
    validate_error(resp, ApiErrorId.ERR_NOTHING_TO_CLAIM.value)


# ===========================================================================
# Difficulty / resource_temporal_overlap — closed cooldown overlap (inclusive)
# ===========================================================================
def test_stake_during_unbonding_cooldown_rejected(api):
    """PRD §3.11: "opening a staking position for an account-and-asset pair is
    rejected with `ERR_STAKE_COOLDOWN_OVERLAP` when an existing `UNBONDING` position
    on that same account and asset has a cooldown interval that contains the current
    clock. This cooldown interval is closed on both endpoints — from
    `unbond_started_at` through `unbond_available_at` inclusive"

    Design: Difficulty/resource_temporal_overlap/staking_closed_cooldown_overlap
    """
    acc = _eth_account_with_balance("2027-02-01T00:00:00Z", amount=200,
                                    email="ov2@x.com", full_name="OV2")
    acc_id = acc["id"]
    trader = make_trader_headers(acc_id)
    pos = setup_staking_position(acc_id, "ETH", 100, 500)
    validate_success(api.unbond_staking_position(pos["id"], trader))
    # cooldown is [2027-02-01, 2027-02-08]; advance to 2027-02-04 (inside)
    set_clock("2027-02-04T00:00:00Z")
    resp = api.create_staking_position(
        {"account_id": acc_id, "asset": "ETH", "principal_amount": 50, "apr_bps": 500},
        trader)
    validate_error(resp, ApiErrorId.ERR_STAKE_COOLDOWN_OVERLAP.value)


def test_stake_at_inclusive_cooldown_endpoint_rejected(api):
    """PRD §3.11: "This cooldown interval is closed on both endpoints — from
    `unbond_started_at` through `unbond_available_at` inclusive — so a stake
    attempted at exactly the `unbond_available_at` instant still collides, in
    contrast to the half-open address hold window of Section 3.5."

    Design: Difficulty/resource_temporal_overlap/staking_closed_cooldown_overlap
    """
    acc = _eth_account_with_balance("2027-02-01T00:00:00Z", amount=200,
                                    email="ov2b@x.com", full_name="OV2B")
    acc_id = acc["id"]
    trader = make_trader_headers(acc_id)
    pos = setup_staking_position(acc_id, "ETH", 100, 500)
    validate_success(api.unbond_staking_position(pos["id"], trader))
    # advance to exactly unbond_available_at = 2027-02-08 (inclusive right endpoint)
    set_clock("2027-02-08T00:00:00Z")
    resp = api.create_staking_position(
        {"account_id": acc_id, "asset": "ETH", "principal_amount": 50, "apr_bps": 500},
        trader)
    validate_error(resp, ApiErrorId.ERR_STAKE_COOLDOWN_OVERLAP.value)
