"""Dividend lifecycle, window overlap, and compensating (reverse) invariants.

Covers the cross-entity-state-dependency (DRIP), resource-temporal-overlap
(dividend window), and compensating-invariant difficulty instances plus the
dividend/options error corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_account_holder_headers,
    create_account, create_security, funded_cash_account, deposit, get_account,
    buy_and_fill, get_first_position,
    announced_dividend, position_with_paid_dividend,
    factories as F,
)


def _holder(account_id):
    return make_account_holder_headers(account_id)


def _clearing():
    return TEST_USERS["clearing_system_headers"]


# --------------------------------------------------------------------------
# Cross-entity: reinvest depends on Position.drip_enabled
# --------------------------------------------------------------------------
def test_reinvest_rejected_when_drip_disabled(api):
    """PRD §3.7: "From `PAID`, the dividend may be reinvested (`PAID → REINVESTED`) when the
    position's `drip_enabled` is true and the computed `reinvest_quantity` is greater than zero;
    if DRIP is not enabled the reinvest is rejected with `ERR_DRIP_NOT_ENABLED`."

    Design: Difficulty/cross_entity_state_dependency/reinvest_depends_on_position_drip_enabled
    """
    account_id, sec_id, position, div = position_with_paid_dividend(
        symbol="NDCO", shares=10, rate_per_share_cents=100, ex_date="2026-04-01T00:00:00Z",
        last_price_cents=10000, drip_enabled=False, deposit_cents=200000,
    )
    assert position["drip_enabled"] is False, position
    resp = api.reinvest_dividend(div["id"], _clearing())
    validate_error(resp, ApiErrorId.ERR_DRIP_NOT_ENABLED, expected_status=409)
    # Dividend remains PAID (no transition).
    divs = get_success_data(api.list_dividends(account_id, _holder(account_id)))
    cur = next(d for d in divs if d["id"] == div["id"])
    assert cur["status"] == "PAID", cur


def test_reinvest_succeeds_when_drip_enabled(api):
    """PRD §3.7: "From `PAID`, the dividend may be reinvested (`PAID → REINVESTED`) when the
    position's `drip_enabled` is true and the computed `reinvest_quantity` is greater than zero."

    Design: Difficulty/cross_entity_state_dependency/reinvest_depends_on_position_drip_enabled
    """
    account_id, sec_id, position, div = position_with_paid_dividend(
        symbol="WDCO", shares=10, rate_per_share_cents=100, ex_date="2026-04-01T00:00:00Z",
        last_price_cents=10000, drip_enabled=True, deposit_cents=200000,
    )
    assert position["drip_enabled"] is True, position
    reinvested = validate_success(api.reinvest_dividend(div["id"], _clearing()))
    assert reinvested["status"] == "REINVESTED", reinvested


# --------------------------------------------------------------------------
# Resource-temporal-overlap: dividend window (half-open)
# --------------------------------------------------------------------------
def test_dividend_window_overlap_same_position_rejected(api):
    """PRD §3.7: "Two non-terminal dividends — those in `ANNOUNCED` or `PAID` status — for the
    same position may not have overlapping windows: a new dividend overlaps an existing
    non-terminal dividend for that position when the new `ex_date` is strictly before the
    existing window's end and the existing `ex_date` is strictly before the new `window_end`.
    Because the interval is half-open, windows that merely touch at an endpoint do not overlap.
    Any overlap rejects the announcement with `ERR_DIVIDEND_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/dividend_window_overlap_same_position_half_open
    """
    # First dividend ex_date 2026-05-01 -> window through 2026-05-31 (ex_date + 30 days).
    account_id, sec_id, position, div1 = announced_dividend(
        symbol="DWCO", shares=10, rate_per_share_cents=50, ex_date="2026-05-01T00:00:00Z",
        last_price_cents=10000, deposit_cents=200000,
    )
    # Second ex_date 2026-05-15 falls strictly inside [2026-05-01, 2026-05-31) -> overlap.
    resp = api.create_dividend(
        F.create_dividend_payload(account_id, position["id"], 50, "2026-05-15T00:00:00Z"),
        _clearing(),
    )
    validate_error(resp, ApiErrorId.ERR_DIVIDEND_WINDOW_OVERLAP, expected_status=409)


def test_dividend_non_overlapping_window_allowed(api):
    """PRD §3.7: "Because the interval is half-open, windows that merely touch at an endpoint do
    not overlap."

    Design: Difficulty/resource_temporal_overlap/dividend_window_overlap_same_position_half_open
    """
    account_id, sec_id, position, div1 = announced_dividend(
        symbol="DWCO2", shares=10, rate_per_share_cents=50, ex_date="2026-05-01T00:00:00Z",
        last_price_cents=10000, deposit_cents=200000,
    )
    # window1 = [2026-05-01, 2026-05-31). A new ex_date of 2026-05-31 touches the endpoint:
    # existing ex_date 2026-05-01 < new window_end, but new ex_date 2026-05-31 is NOT strictly
    # before existing window_end 2026-05-31 -> no overlap -> allowed.
    div2 = validate_success(
        api.create_dividend(
            F.create_dividend_payload(account_id, position["id"], 50, "2026-05-31T00:00:00Z"),
            _clearing()),
        expected_status=201,
    )
    assert div2["status"] == "ANNOUNCED", div2


# --------------------------------------------------------------------------
# Compensating invariant 1: deposit reverse conserves instant_credit
# --------------------------------------------------------------------------
def test_deposit_reverse_conserves_instant_credit_pool(api):
    """PRD §3.1: "the `ClearingSystem` may report an ACH return on a still-`PENDING` deposit,
    transitioning it to `REVERSED`: the provisional `instant_credit_granted_cents` is clawed back
    from `instant_credit_cents`, buying power is recomputed."

    Design: Difficulty/compensating_invariant/deposit_reverse_conserves_instant_credit_pool
    """
    acc = create_account(account_type="CASH")
    dep = validate_success(
        api.create_deposit(acc["id"], F.create_deposit_payload(amount_cents=400000, instant_eligible=True),
                           _holder(acc["id"])),
        expected_status=201,
    )
    before = get_account(acc["id"])
    assert before["instant_credit_cents"] == 400000, before

    reversed_dep = validate_success(api.reverse_deposit(dep["id"], _clearing()))
    assert reversed_dep["status"] == "REVERSED", reversed_dep
    after = get_account(acc["id"])
    # Forward grant + reverse clawback = 0 net.
    assert after["instant_credit_cents"] == 0, after
    # Buying power likewise returns to 0 (CASH = settled 0 + instant_credit 0).
    assert after["buying_power_cents"] == 0, after


def test_reverse_already_reversed_deposit_rejected(api):
    """PRD §3.1: "A deposit that has already left `PENDING` cannot be reversed; attempting a
    transition on a wrong-status deposit is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/deposit_reverse_conserves_instant_credit_pool
    """
    acc = create_account(account_type="CASH")
    dep = validate_success(
        api.create_deposit(acc["id"], F.create_deposit_payload(amount_cents=400000, instant_eligible=True),
                           _holder(acc["id"])),
        expected_status=201,
    )
    validate_success(api.reverse_deposit(dep["id"], _clearing()))
    # Second reverse on a now-REVERSED deposit is a wrong-status transition.
    resp = api.reverse_deposit(dep["id"], _clearing())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


# --------------------------------------------------------------------------
# Compensating invariant 2: dividend pay+reverse conserves settled_cash
# --------------------------------------------------------------------------
def test_dividend_pay_reverse_conserves_settled_cash(api):
    """PRD §3.7: "Paying moves it `ANNOUNCED → PAID`: this requires the event to be `ANNOUNCED`
    with a `record_quantity` greater than zero, adds the `gross_amount_cents` to
    `settled_cash_cents`."
    PRD §3.7: "a `PAID` dividend that has not yet been reinvested may be reversed
    (`PAID → REVERSED`) as a correction, which subtracts the `gross_amount_cents` back out of
    `settled_cash_cents` to compensate the earlier pay credit."

    Design: Difficulty/compensating_invariant/dividend_pay_reverse_conserves_settled_cash
    """
    # Build a position whose settled cash is known: deposit 200000 settled (after clock),
    # then buy 10 sh @ 10000c (spend 100000 settled). Use the fixture and inspect.
    from test_helpers import advance_clock
    sec = create_security(symbol="PRVCO", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=200000)
    buy_and_fill(account_id, sec["id"], 10, 10000, order_type="MARKET")
    # Advance so both deposit and the BUY DEBIT settle.
    advance_clock("2026-01-07T00:00:00Z")
    before = get_account(account_id)
    sc_before = before["settled_cash_cents"]

    position = get_first_position(account_id)
    div = validate_success(
        api.create_dividend(
            F.create_dividend_payload(account_id, position["id"], 100, "2026-06-01T00:00:00Z"),
            _clearing()),
        expected_status=201,
    )
    paid = validate_success(api.pay_dividend(div["id"], _clearing()))
    after_pay = get_account(account_id)
    assert after_pay["settled_cash_cents"] == sc_before + 1000, (sc_before, after_pay)

    reversed_div = validate_success(api.reverse_dividend(div["id"], _clearing()))
    assert reversed_div["status"] == "REVERSED", reversed_div
    after_reverse = get_account(account_id)
    assert after_reverse["settled_cash_cents"] == sc_before, (sc_before, after_reverse)


def test_dividend_pay_credits_gross_to_settled_cash(api):
    """PRD §3.7: "Paying moves it `ANNOUNCED → PAID`: this requires the event to be `ANNOUNCED`
    with a `record_quantity` greater than zero, adds the `gross_amount_cents` to
    `settled_cash_cents`, recomputes buying power, and increments the account `version`."

    Design: Difficulty/compensating_invariant/dividend_pay_reverse_conserves_settled_cash
    """
    account_id, sec_id, position, div = announced_dividend(
        symbol="PAYG", shares=10, rate_per_share_cents=100, ex_date="2026-06-01T00:00:00Z",
        last_price_cents=10000, deposit_cents=200000,
    )
    assert div["status"] == "ANNOUNCED", div
    assert div["gross_amount_cents"] == 1000, div
    before = get_account(account_id)
    paid = validate_success(api.pay_dividend(div["id"], _clearing()))
    assert paid["status"] == "PAID", paid
    after = get_account(account_id)
    assert after["settled_cash_cents"] == before["settled_cash_cents"] + 1000, (before, after)


# --------------------------------------------------------------------------
# Dividend / options error corners
# --------------------------------------------------------------------------
def test_pay_already_paid_dividend_rejected(api):
    """PRD §3.7: "Attempting to pay, reinvest, or reverse a dividend that is not in the
    appropriate status is rejected with `ERR_DIVIDEND_NOT_PAYABLE`."

    Design: Corner/errors/pay_already_paid_dividend_rejected
    """
    account_id, sec_id, position, paid = position_with_paid_dividend(
        symbol="PAYCO", shares=10, rate_per_share_cents=100, ex_date="2026-08-01T00:00:00Z",
        last_price_cents=10000, drip_enabled=False, deposit_cents=200000,
    )
    assert paid["status"] == "PAID", paid
    resp = api.pay_dividend(paid["id"], _clearing())
    validate_error(resp, ApiErrorId.ERR_DIVIDEND_NOT_PAYABLE, expected_status=409)


def test_options_requested_level_out_of_range_rejected(api):
    """PRD §3.8: "The requested level must be 1, 2, or 3; a requested level outside that range is
    rejected with `ERR_OPTIONS_LEVEL_TOO_HIGH`."

    Design: Corner/errors/options_requested_level_out_of_range_rejected
    """
    acc = create_account(account_type="CASH")
    resp = api.create_options_approval(
        F.create_options_approval_payload(acc["id"], 4, 5, 20_000_000),
        _holder(acc["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_OPTIONS_LEVEL_TOO_HIGH, expected_status=422)
