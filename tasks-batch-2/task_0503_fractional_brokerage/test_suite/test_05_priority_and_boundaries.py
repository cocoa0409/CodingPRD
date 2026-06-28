"""Validation-priority conflicts, numeric boundaries (PDT, instant credit).

Covers the priority-pair and boundary-precision difficulty instances plus the
related instant-credit boundary corner.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_account_holder_headers,
    create_account, create_security, funded_cash_account, settled_margin_account,
    deposit, get_account, get_account_version, place_order, fill_order, advance_clock,
    factories as F,
    INSTANT_CAP_CENTS,
)


def _holder(account_id):
    return make_account_holder_headers(account_id)


def _compliance():
    return TEST_USERS["compliance_officer_headers"]


def _clearing():
    return TEST_USERS["clearing_system_headers"]


# --------------------------------------------------------------------------
# Priority-pair conflicts
# --------------------------------------------------------------------------
def test_stale_version_beats_frozen_block(api):
    """PRD §2.7: "Fifth, optimistic-concurrency version match where required, else
    `ERR_STALE_ACCOUNT_VERSION`. Sixth, target-resource state legality for the requested
    transition, else `ERR_INVALID_STATE`. Only after all six of these gates pass does the system
    evaluate the operation-specific business rules described in §3 (frozen-account, restriction,
    options-level, order-shape, share-sufficiency, buying-power, and the various temporal and
    fiscal checks)."
    PRD §2.8: "if that value does not equal the account's current `version`, the order is
    rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412."

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_beats_frozen_block
    """
    sec = create_security(symbol="PRCO", last_price_cents=10000, fractional_enabled=True)
    acc = create_account(account_type="CASH")
    deposit(acc["id"], 100000, instant_eligible=True)
    pre_version = get_account_version(acc["id"])
    # Freeze the account (bumps version).
    validate_success(api.set_compliance_hold(acc["id"], F.compliance_hold_payload(True), _compliance()))
    # Order carries the stale pre-freeze version AND the account is FROZEN.
    resp = api.create_order(
        F.create_order_payload(acc["id"], sec["id"], pre_version, side="BUY", order_type="MARKET",
                               quantity=1),
        _holder(acc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION, expected_status=412)


def test_frozen_account_with_current_version_surfaces_frozen(api):
    """PRD §2.7: "Fifth, optimistic-concurrency version match where required, else
    `ERR_STALE_ACCOUNT_VERSION`. Sixth, target-resource state legality for the requested
    transition, else `ERR_INVALID_STATE`. Only after all six of these gates pass does the system
    evaluate the operation-specific business rules described in §3 (frozen-account, restriction,
    options-level, order-shape, share-sufficiency, buying-power, and the various temporal and
    fiscal checks)."
    PRD §3.3: "If the account's posture is `FROZEN`, all order placement is blocked with
    `ERR_ACCOUNT_FROZEN`."

    Design: Difficulty/priority_pair_validation_conflict/occ_stale_beats_frozen_block
    """
    sec = create_security(symbol="PRCO2", last_price_cents=10000, fractional_enabled=True)
    acc = create_account(account_type="CASH")
    deposit(acc["id"], 100000, instant_eligible=True)
    validate_success(api.set_compliance_hold(acc["id"], F.compliance_hold_payload(True), _compliance()))
    # OCC passes (current version) so the FROZEN business gate is what fires.
    current_version = get_account_version(acc["id"])
    resp = api.create_order(
        F.create_order_payload(acc["id"], sec["id"], current_version, side="BUY",
                               order_type="MARKET", quantity=1),
        _holder(acc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_FROZEN, expected_status=409)


def test_options_level_beats_buying_power(api):
    """PRD §3.3: "For an `OPTION` security, the account's `options_level` must be at least the
    security's `required_options_level`, else the order is rejected with
    `ERR_OPTIONS_LEVEL_INSUFFICIENT`."
    PRD §3.3: "when several apply, the lower-numbered priority wins, so a frozen account surfaces
    `ERR_ACCOUNT_FROZEN` ahead of a restriction, options, shape, share, or buying-power failure."

    Design: Difficulty/priority_pair_validation_conflict/options_level_beats_buying_power
    """
    sec = create_security(symbol="OPT1", instrument_type="OPTION", last_price_cents=50000,
                          fractional_enabled=False, required_options_level=2)
    acc = create_account(account_type="CASH")  # $0 buying power, options_level 0
    version = get_account_version(acc["id"])
    resp = api.create_order(
        F.create_order_payload(acc["id"], sec["id"], version, side="BUY", order_type="LIMIT",
                               quantity=100, limit_price_cents=50000),
        _holder(acc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OPTIONS_LEVEL_INSUFFICIENT, expected_status=409)


def test_buying_power_check_fires_on_equity_security_when_options_passes(api):
    """PRD §3.3: "Finally, for a BUY, the required cash to reserve must not exceed the account's
    `buying_power_cents`, else `ERR_INSUFFICIENT_BUYING_POWER`."
    PRD §3.3: "when several apply, the lower-numbered priority wins, so a frozen account surfaces
    `ERR_ACCOUNT_FROZEN` ahead of a restriction, options, shape, share, or buying-power failure."

    Design: Difficulty/priority_pair_validation_conflict/options_level_beats_buying_power
    """
    # On an EQUITY (required_options_level 0) the options gate passes, so the SAME
    # under-funded order surfaces the buying-power error instead — confirming options-level
    # precedes buying-power only when the option gate actually applies.
    sec = create_security(symbol="EQBP", instrument_type="EQUITY", last_price_cents=50000,
                          fractional_enabled=False)
    acc = create_account(account_type="CASH")  # $0 buying power
    version = get_account_version(acc["id"])
    resp = api.create_order(
        F.create_order_payload(acc["id"], sec["id"], version, side="BUY", order_type="LIMIT",
                               quantity=100, limit_price_cents=50000),
        _holder(acc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BUYING_POWER, expected_status=402)


# --------------------------------------------------------------------------
# Boundary: PDT equity threshold
# --------------------------------------------------------------------------
def test_pdt_equity_exactly_25000_does_not_flag(api):
    """PRD §3.9: "The account becomes `pdt_flagged` when the `day_trade_count` reaches the PDT
    threshold of 4 and the `account_equity_cents` is below the PDT minimum equity of twenty-five
    thousand dollars (two and a half million cents). The boundaries are exact: exactly 4 day
    trades flags, and equity of exactly twenty-five thousand dollars does not flag because the
    minimum-equity test clears at or above that figure."
    PRD §3.9: "On a closing fill, if an opening fill of the same security exists with the same
    logical-clock date, the system increments `day_trade_count`."

    Design: Difficulty/boundary_precision_check/pdt_equity_exactly_25000_does_not_flag
    """
    sec = create_security(symbol="PDTCO", last_price_cents=10000, fractional_enabled=True)
    acc = create_account(account_type="CASH")
    deposit(acc["id"], 2_500_000, instant_eligible=True)
    advance_clock("2026-01-05T00:00:00Z")  # settle the deposit -> settled_cash 2,500,000
    account_id = acc["id"]

    # Four same-day round trips (BUY then closing SELL of 1 sh each at 10000c, no P/L).
    for _ in range(4):
        v = get_account_version(account_id)
        b = place_order(account_id, sec["id"], v, side="BUY", order_type="MARKET", quantity=1)
        fill_order(b["id"], 1, 10000)
        v = get_account_version(account_id)
        s = place_order(account_id, sec["id"], v, side="SELL", order_type="MARKET",
                        quantity=1, is_closing=True)
        fill_order(s["id"], 1, 10000)

    acc_after = get_account(account_id)
    assert acc_after["day_trade_count"] == 4, acc_after
    assert acc_after["account_equity_cents"] == 2_500_000, acc_after
    # Equity exactly at the floor -> NOT flagged.
    assert acc_after["pdt_flagged"] is False, acc_after


def test_single_round_trip_counts_one_day_trade(api):
    """PRD §3.9: "A day trade is a same-security open-and-close (a BUY-to-open and SELL-to-close,
    or a short open and cover) of the same security within the same logical-clock calendar date.
    On a closing fill, if an opening fill of the same security exists with the same logical-clock
    date, the system increments `day_trade_count` and sets that order's `opened_day_trade` to
    true."

    Design: Difficulty/boundary_precision_check/pdt_equity_exactly_25000_does_not_flag
    """
    sec = create_security(symbol="DTCNT", last_price_cents=10000, fractional_enabled=True)
    acc = create_account(account_type="CASH")
    deposit(acc["id"], 2_500_000, instant_eligible=True)
    advance_clock("2026-01-05T00:00:00Z")
    account_id = acc["id"]

    v = get_account_version(account_id)
    b = place_order(account_id, sec["id"], v, side="BUY", order_type="MARKET", quantity=1)
    fill_order(b["id"], 1, 10000)
    v = get_account_version(account_id)
    s = place_order(account_id, sec["id"], v, side="SELL", order_type="MARKET",
                    quantity=1, is_closing=True)
    fill_order(s["id"], 1, 10000)

    acc_after = get_account(account_id)
    assert acc_after["day_trade_count"] == 1, acc_after
    # Below threshold of 4 -> not flagged regardless of equity.
    assert acc_after["pdt_flagged"] is False, acc_after


# --------------------------------------------------------------------------
# Boundary: instant-credit cumulative cap
# --------------------------------------------------------------------------
def test_instant_credit_exactly_at_cap_allowed(api):
    """PRD §3.1: "if the request exceeds the headroom it is rejected with
    `ERR_INSTANT_LIMIT_EXCEEDED`, and the boundary is inclusive — a request exactly equal to the
    remaining headroom is allowed, while a request one cent greater is rejected. Otherwise
    `instant_credit_granted_cents` is set to the requested amount."

    Design: Difficulty/boundary_precision_check/instant_credit_exactly_at_cap_then_one_over_rejected
    """
    acc = create_account(account_type="CASH")
    dep = validate_success(
        api.create_deposit(acc["id"], F.create_deposit_payload(amount_cents=INSTANT_CAP_CENTS,
                                                               instant_eligible=True),
                           _holder(acc["id"])),
        expected_status=201,
    )
    assert dep["instant_credit_granted_cents"] == INSTANT_CAP_CENTS, dep


def test_instant_credit_one_over_cap_rejected(api):
    """PRD §3.1: "if the request exceeds the headroom it is rejected with
    `ERR_INSTANT_LIMIT_EXCEEDED`, and the boundary is inclusive — a request exactly equal to the
    remaining headroom is allowed, while a request one cent greater is rejected."

    Design: Difficulty/boundary_precision_check/instant_credit_exactly_at_cap_then_one_over_rejected
    """
    acc = create_account(account_type="CASH")
    # First deposit consumes the entire cap.
    validate_success(
        api.create_deposit(acc["id"], F.create_deposit_payload(amount_cents=INSTANT_CAP_CENTS,
                                                               instant_eligible=True),
                           _holder(acc["id"])),
        expected_status=201,
    )
    # Headroom now 0; one more cent of instant credit is rejected.
    resp = api.create_deposit(
        acc["id"], F.create_deposit_payload(amount_cents=1, instant_eligible=True),
        _holder(acc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSTANT_LIMIT_EXCEEDED, expected_status=402)
