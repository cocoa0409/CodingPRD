"""Margin maintenance, the trading posture cycle, margin calls, liquidation.

Covers the non-linear-state-machine (cyclic posture), transitive-cascade
(quote->margin-call), cross-entity-state-dependency, resource-temporal-overlap
difficulty instances and the margin error corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_account_holder_headers,
    create_security, settled_margin_account, place_order, fill_order,
    get_account_version, update_quote,
    margin_account_holding, margin_account_in_deficiency, margin_account_with_issued_call,
    factories as F,
)


def _holder(account_id):
    return make_account_holder_headers(account_id)


def _clearing():
    return TEST_USERS["clearing_system_headers"]


def _market_data():
    return TEST_USERS["market_data_headers"]


def test_posture_drops_to_restricted_then_returns_to_active(api):
    """PRD §3.10: "From `ACTIVE`, the posture moves to `RESTRICTED_CLOSING_ONLY` when a recompute
    after a fill or quote drives `maintenance_excess_cents` below zero or sets the PDT flag."
    PRD §3.10: "the posture returns from `RESTRICTED_CLOSING_ONLY` to `ACTIVE` once
    `maintenance_excess_cents` is at or above zero and the PDT flag is cleared and the compliance
    hold is clear."

    Design: Difficulty/non_linear_state_machine/account_trading_status_restricted_then_back_to_active_cycle
    """
    # MARGIN account holding 100 sh of MARG @ 10000c (deposit 5000.00). After fill:
    # settled_cash -500000, market_value 1000000, maintenance 25% -> 250000, excess 250000.
    account_id, security_id = margin_account_holding(
        symbol="MARG", shares=100, fill_price_cents=10000, maintenance_rate_bps=2500,
        deposit_cents=500000,
    )
    # Quote drop to 4000c: mv 400000, maintenance 100000, equity -500000+400000=-100000,
    # excess -100000-100000 = -200000 -> RESTRICTED_CLOSING_ONLY.
    update_quote(security_id, 4000)
    low = validate_success(api.get_account(account_id, _holder(account_id)))
    assert low["maintenance_excess_cents"] == -200000, low
    assert low["trading_status"] == "RESTRICTED_CLOSING_ONLY", low

    # Quote restored to 10000c: excess back to 250000 -> ACTIVE (cycle returned).
    update_quote(security_id, 10000)
    back = validate_success(api.get_account(account_id, _holder(account_id)))
    assert back["maintenance_excess_cents"] == 250000, back
    assert back["trading_status"] == "ACTIVE", back


def test_restricted_posture_blocks_opening_buy_but_active_allows_it(api):
    """PRD §3.10: "while restricted, opening BUY orders are rejected with
    `ERR_RESTRICTED_CLOSING_ONLY` and only closing SELLs are accepted."
    PRD §3.3: "an opening BUY requires the posture to be `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/account_trading_status_restricted_then_back_to_active_cycle
    """
    account_id, security_id = margin_account_holding(
        symbol="MARGC", shares=100, fill_price_cents=10000, maintenance_rate_bps=2500,
        deposit_cents=500000,
    )
    # Drop the quote -> RESTRICTED; an opening BUY must be refused.
    update_quote(security_id, 4000)
    v_low = get_account_version(account_id)
    blocked = api.create_order(
        F.create_order_payload(account_id, security_id, v_low, side="BUY", order_type="LIMIT",
                               quantity=1, limit_price_cents=4000),
        _holder(account_id),
    )
    validate_error(blocked, ApiErrorId.ERR_RESTRICTED_CLOSING_ONLY, expected_status=409)
    # Restore the quote -> ACTIVE again; the same opening BUY is now accepted.
    update_quote(security_id, 10000)
    v_active = get_account_version(account_id)
    accepted = validate_success(api.create_order(
        F.create_order_payload(account_id, security_id, v_active, side="BUY", order_type="LIMIT",
                               quantity=1, limit_price_cents=10000),
        _holder(account_id)),
        expected_status=201,
    )
    assert accepted["order_status"] == "ACCEPTED", accepted


def test_quote_drop_cascades_to_margin_call_and_posture(api):
    """PRD §3.2: "for every `Position` held on that security, the system recomputes the
    position's `market_value_cents`, then recomputes each affected account's equity, maintenance
    requirement, maintenance excess, buying power, and finally its trading posture."
    PRD §3.9: "On successful issuance the call records its `account_id`, a `deficiency_cents`
    equal to the absolute value of `maintenance_excess_cents` at issuance, a `cure_by` of the
    logical clock date plus the margin cure period of 4 business days, and a `status` of
    `ISSUED`, and the account's trading posture moves to `MARGIN_CALL`."

    Design: Difficulty/transitive_cascade/quote_drop_cascades_to_margin_call_depth3
    """
    account_id, security_id = margin_account_holding(
        symbol="CASG", shares=100, fill_price_cents=10000, maintenance_rate_bps=2500,
        deposit_cents=500000,
    )
    update_quote(security_id, 4000)
    # Link 1: Position market value.
    pos = get_success_data(api.list_positions(_holder(account_id), params={"account_id": account_id}))[0]
    assert pos["market_value_cents"] == 400000, pos
    # Link 2: account maintenance excess.
    acc = validate_success(api.get_account(account_id, _holder(account_id)))
    assert acc["maintenance_excess_cents"] == -200000, acc
    # Link 3: issue the call -> deficiency + posture.
    call = validate_success(api.issue_margin_call(account_id, _clearing()), expected_status=201)
    assert call["deficiency_cents"] == 200000, call
    acc_after = validate_success(api.get_account(account_id, _holder(account_id)))
    assert acc_after["trading_status"] == "MARGIN_CALL", acc_after


def test_quote_drop_recomputes_position_market_value_and_excess(api):
    """PRD §3.9: "where each `market_value_cents` is the position `quantity` multiplied by the
    security's `last_price_cents` rounded half up. The maintenance requirement is the sum over
    positions of each position's `market_value_cents` multiplied by the security's
    `maintenance_rate_bps` divided by 10000, rounded half up to whole cents. The maintenance
    excess is the account equity minus the maintenance requirement."

    Design: Difficulty/transitive_cascade/quote_drop_cascades_to_margin_call_depth3
    """
    account_id, security_id = margin_account_holding(
        symbol="CASG2", shares=100, fill_price_cents=10000, maintenance_rate_bps=2500,
        deposit_cents=500000,
    )
    before = validate_success(api.get_account(account_id, _holder(account_id)))
    assert before["maintenance_excess_cents"] == 250000, before
    update_quote(security_id, 4000)
    pos = get_success_data(api.list_positions(_holder(account_id), params={"account_id": account_id}))[0]
    # Link 1: market value 100 * 4000 = 400000.
    assert pos["market_value_cents"] == 400000, pos
    after = validate_success(api.get_account(account_id, _holder(account_id)))
    # equity = -500000 (settled) + 400000 (mv) = -100000; maintenance = 400000*2500/10000 = 100000.
    assert after["maintenance_requirement_cents"] == 100000, after
    assert after["maintenance_excess_cents"] == -200000, after


def test_opening_buy_blocked_under_restricted_closing_only(api):
    """PRD §3.3: "If the posture is `RESTRICTED_CLOSING_ONLY` or `MARGIN_CALL`, an opening BUY is
    blocked and only a SELL marked `is_closing` is accepted, with the rejection carried as
    `ERR_RESTRICTED_CLOSING_ONLY`; equivalently, an opening BUY requires the posture to be
    `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/order_placement_depends_on_account_trading_status
    """
    account_id, security_id = margin_account_in_deficiency(
        symbol="DEPCO", shares=100, original_price_cents=10000, dropped_price_cents=4000,
        maintenance_rate_bps=2500, deposit_cents=500000,
    )
    before = validate_success(api.get_account(account_id, _holder(account_id)))
    assert before["trading_status"] == "RESTRICTED_CLOSING_ONLY", before
    version = before["version"]
    resp = api.create_order(
        F.create_order_payload(account_id, security_id, version, side="BUY", order_type="LIMIT",
                               quantity=1, limit_price_cents=4000),
        _holder(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_RESTRICTED_CLOSING_ONLY, expected_status=409)


def test_closing_sell_accepted_under_restricted_closing_only(api):
    """PRD §3.3: "If the posture is `RESTRICTED_CLOSING_ONLY` or `MARGIN_CALL`, an opening BUY is
    blocked and only a SELL marked `is_closing` is accepted, with the rejection carried as
    `ERR_RESTRICTED_CLOSING_ONLY`."

    Design: Difficulty/cross_entity_state_dependency/order_placement_depends_on_account_trading_status
    """
    account_id, security_id = margin_account_in_deficiency(
        symbol="DEPCS", shares=100, original_price_cents=10000, dropped_price_cents=4000,
        maintenance_rate_bps=2500, deposit_cents=500000,
    )
    version = get_account_version(account_id)
    sell = validate_success(api.create_order(
        F.create_order_payload(account_id, security_id, version, side="SELL", order_type="LIMIT",
                               quantity=1, limit_price_cents=4000, is_closing=True),
        _holder(account_id)),
        expected_status=201,
    )
    assert sell["order_status"] == "ACCEPTED", sell


def test_second_margin_call_blocked_single_occupancy(api):
    """PRD §3.9: "The cure window is single-occupancy with capacity one: a new call collides if
    any `MarginCall` in status `ISSUED` already occupies the account's cure window ... and such a
    collision is rejected with `ERR_MARGIN_CALL_ACTIVE`; a second issued call may never coexist
    with a first."

    Design: Difficulty/resource_temporal_overlap/margin_call_active_blocks_second_issue_single_occupancy
    """
    account_id, security_id, first = margin_account_with_issued_call(
        symbol="MCCO", shares=100, original_price_cents=10000, dropped_price_cents=4000,
        maintenance_rate_bps=2500, deposit_cents=500000,
    )
    assert first["status"] == "ISSUED", first
    assert first["deficiency_cents"] == 200000, first
    resp = api.issue_margin_call(account_id, _clearing())
    validate_error(resp, ApiErrorId.ERR_MARGIN_CALL_ACTIVE, expected_status=409)


def test_first_issued_call_remains_sole_occupant_after_blocked_second(api):
    """PRD §3.9: "a new call collides if any `MarginCall` in status `ISSUED` already occupies the
    account's cure window ... and such a collision is rejected with `ERR_MARGIN_CALL_ACTIVE`; a
    second issued call may never coexist with a first."

    Design: Difficulty/resource_temporal_overlap/margin_call_active_blocks_second_issue_single_occupancy
    """
    account_id, security_id, first = margin_account_with_issued_call(
        symbol="MCCO2", shares=100, original_price_cents=10000, dropped_price_cents=4000,
        maintenance_rate_bps=2500, deposit_cents=500000,
    )
    blocked = api.issue_margin_call(account_id, _clearing())
    validate_error(blocked, ApiErrorId.ERR_MARGIN_CALL_ACTIVE, expected_status=409)
    # Only the first ISSUED call exists for the account.
    calls = get_success_data(api.list_margin_calls(account_id, _holder(account_id)))
    issued = [c for c in calls if c["status"] == "ISSUED"]
    assert len(issued) == 1, calls
    assert issued[0]["id"] == first["id"], (issued, first)


def test_issue_margin_call_without_deficiency_rejected(api):
    """PRD §3.9: "Issuance requires the account's `maintenance_excess_cents` to be below zero,
    else it is rejected with `ERR_NO_DEFICIENCY`."

    Design: Corner/errors/issue_margin_call_without_deficiency_rejected
    """
    # MARGIN account funded, no positions -> excess >= 0.
    account_id, _v = settled_margin_account(amount_cents=500000)
    resp = api.issue_margin_call(account_id, _clearing())
    validate_error(resp, ApiErrorId.ERR_NO_DEFICIENCY, expected_status=409)


def test_liquidate_before_cure_by_rejected(api):
    """PRD §3.9: "an attempt to liquidate before `cure_by` or when the excess is already
    non-negative is rejected with `ERR_MARGIN_CALL_NOT_DUE`."

    Design: Corner/errors/liquidate_before_cure_by_rejected
    """
    account_id, security_id, call = margin_account_with_issued_call(
        symbol="LIQCO", shares=100, original_price_cents=10000, dropped_price_cents=4000,
        maintenance_rate_bps=2500, deposit_cents=500000,
    )
    # Clock is at 2026-01-05 (set by settled_margin_account); cure_by is +4 business days.
    resp = api.liquidate_margin_call(account_id, call["id"], _clearing())
    validate_error(resp, ApiErrorId.ERR_MARGIN_CALL_NOT_DUE, expected_status=409)
