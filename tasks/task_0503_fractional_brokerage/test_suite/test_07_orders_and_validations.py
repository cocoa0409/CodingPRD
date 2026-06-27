"""Order shape, placement validations, terminal-state guards, and endpoints.

Covers the entities / state_machines / validations / endpoints corner probes.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_account_holder_headers,
    create_account, create_security, funded_cash_account, deposit,
    get_account, get_account_version, place_order, fill_order, buy_and_fill,
    factories as F,
)


def _holder(account_id):
    return make_account_holder_headers(account_id)


def _clearing():
    return TEST_USERS["clearing_system_headers"]


# --------------------------------------------------------------------------
# Entities corners
# --------------------------------------------------------------------------
def test_security_immutable_no_version_field(api):
    """PRD §2.4: "Two entities are reference/configuration records that never mutate after
    creation and therefore carry only `id` and `created_at` — they expose neither `updated_at`
    nor `version`. The first is the `Security`, a tradable instrument definition; note that the
    quote endpoint does update a security's `last_price_cents` in place, but the security still
    exposes only `id` and `created_at` and does not carry a `version`."

    Design: Corner/entities/security_immutable_no_version_field
    """
    resp = api.create_security(
        F.create_security_payload(symbol="IMMU", instrument_type="EQUITY", last_price_cents=5000),
        _clearing(),
    )
    sec = validate_success(resp, expected_status=201)
    assert "created_at" in sec, sec
    assert "version" not in sec, sec
    assert "updated_at" not in sec, sec


def test_order_notional_and_quantity_both_set_returns_422(api):
    """PRD §3.3: "Exactly one of `notional_cents` and `quantity` must be provided; supplying
    both, or neither (both zero), is a malformed body rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/order_notional_and_quantity_both_set_returns_422
    """
    sec = create_security(symbol="XORCO", last_price_cents=10000, fractional_enabled=True)
    account_id, version = funded_cash_account(amount_cents=100000)
    resp = api.create_order(
        F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="MARKET",
                               notional_cents=50000, quantity=5),
        _holder(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=422)


# --------------------------------------------------------------------------
# State-machine corners
# --------------------------------------------------------------------------
def test_cancel_filled_order_returns_invalid_state(api):
    """PRD §2.7: "Sixth, target-resource state legality for the requested transition, else
    `ERR_INVALID_STATE`."
    PRD §3.5: "An accepted order may also be cancelled by its holder while non-terminal;
    cancellation moves it from `ACCEPTED` or `PARTIALLY_FILLED` to `CANCELLED`."

    Design: Corner/state_machines/cancel_terminal_order_returns_invalid_state
    """
    sec = create_security(symbol="TERMCO", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=100000)
    order, _fill = buy_and_fill(account_id, sec["id"], 1, 10000, order_type="MARKET")
    # Order is now FILLED (terminal); cancel must be rejected.
    filled = validate_success(api.get_order(order["id"], _holder(account_id)))
    assert filled["order_status"] == "FILLED", filled
    resp = api.cancel_order(order["id"], _holder(account_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_fill_on_terminal_order_returns_cannot_fill_terminal(api):
    """PRD §3.5: "A fill cannot be reported against a terminal order — one already `FILLED`,
    `REJECTED`, or `CANCELLED` — and such an attempt is rejected with `ERR_CANNOT_FILL_TERMINAL`."

    Design: Corner/state_machines/fill_on_terminal_order_returns_cannot_fill_terminal
    """
    sec = create_security(symbol="FILLC", last_price_cents=10000, fractional_enabled=True)
    account_id, version = funded_cash_account(amount_cents=100000)
    order = place_order(account_id, sec["id"], version, side="BUY", order_type="MARKET", quantity=1)
    validate_success(api.cancel_order(order["id"], _holder(account_id)))
    # Fill against a CANCELLED order.
    resp = api.create_fill(order["id"], F.create_fill_payload(1, 10000), _clearing())
    validate_error(resp, ApiErrorId.ERR_CANNOT_FILL_TERMINAL, expected_status=409)


def test_settlement_leg_not_due_remains_unsettled(api):
    """PRD §3.6: "A leg whose `settles_on` is still in the future is left `UNSETTLED`."
    PRD §3.6: "Each `Settlement` records its `account_id`, the originating `fill_id`, a
    `direction` ... a `settles_on` of trade date plus one business day, and a `status` that
    begins `UNSETTLED`."

    Design: Corner/state_machines/settle_before_due_returns_settlement_not_due
    """
    sec = create_security(symbol="SETCO", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=100000)
    buy_and_fill(account_id, sec["id"], 1, 10000, order_type="MARKET")
    # Clock is still 2026-01-01; settles_on is 2026-01-02 (T+1), so the leg stays UNSETTLED.
    settlements = get_success_data(api.list_settlements(account_id, _holder(account_id)))
    assert len(settlements) >= 1, settlements
    assert settlements[0]["status"] == "UNSETTLED", settlements[0]


def test_order_initial_state_is_accepted_with_reservation(api):
    """PRD §3.3: "When every gate passes, the order transitions `PENDING_NEW → ACCEPTED`: a
    routing venue is selected (see §3.4), and for a BUY the required cash is locked as
    `reserved_buying_power_cents` and the account's `buying_power_cents` decreases by that
    reservation."
    PRD §3.4: "for a notional order it is simply the `notional_cents`."

    Design: Corner/state_machines/order_initial_state_is_pending_new_then_accepted
    """
    sec = create_security(symbol="INITCO", last_price_cents=10000, fractional_enabled=True)
    account_id, version = funded_cash_account(amount_cents=100000)
    order = validate_success(
        api.create_order(
            F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="MARKET",
                                   notional_cents=50000),
            _holder(account_id)),
        expected_status=201,
    )
    assert order["order_status"] == "ACCEPTED", order
    assert order["reserved_buying_power_cents"] == 50000, order
    assert order["pfof_venue"] == "VENUE_A", order


# --------------------------------------------------------------------------
# Validation corners (order-shape and fiscal)
# --------------------------------------------------------------------------
def test_extended_hours_market_order_rejected(api):
    """PRD §3.3: "An `EXTENDED`-session order is accepted only when the security is
    `extended_hours_eligible` and the order_type is `LIMIT`; an extended order that is not a
    limit, or whose security is not extended-hours eligible, is rejected with
    `ERR_EXTENDED_HOURS_LIMIT_ONLY`."

    Design: Corner/validations/extended_hours_market_order_rejected
    """
    sec = create_security(symbol="EXTCO", last_price_cents=10000, fractional_enabled=True,
                          extended_hours_eligible=True)
    account_id, version = funded_cash_account(amount_cents=100000)
    resp = api.create_order(
        F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="MARKET",
                               quantity=1, session="EXTENDED"),
        _holder(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_EXTENDED_HOURS_LIMIT_ONLY, expected_status=422)


def test_fractional_on_non_fractional_security_rejected(api):
    """PRD §3.3: "A notional (dollar-fractional) order is permitted only on a security whose
    `fractional_enabled` is true, otherwise it is rejected with `ERR_FRACTIONAL_NOT_ALLOWED`."

    Design: Corner/validations/fractional_on_non_fractional_security_rejected
    """
    sec = create_security(symbol="NOFRAC", last_price_cents=10000, fractional_enabled=False)
    account_id, version = funded_cash_account(amount_cents=100000)
    resp = api.create_order(
        F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="MARKET",
                               notional_cents=50000),
        _holder(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_FRACTIONAL_NOT_ALLOWED, expected_status=422)


def test_limit_order_without_price_rejected(api):
    """PRD §3.3: "A `LIMIT` order requires `limit_price_cents` to be strictly greater than zero,
    else `ERR_LIMIT_PRICE_REQUIRED`."

    Design: Corner/validations/limit_order_without_price_rejected
    """
    sec = create_security(symbol="LIMCO", last_price_cents=10000, fractional_enabled=True)
    account_id, version = funded_cash_account(amount_cents=100000)
    resp = api.create_order(
        F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="LIMIT",
                               quantity=1),
        _holder(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_LIMIT_PRICE_REQUIRED, expected_status=422)


def test_sell_more_than_held_rejected(api):
    """PRD §3.3: "For a SELL, the requested share count must not exceed the available
    `Position.quantity`, else `ERR_INSUFFICIENT_SHARES`."

    Design: Corner/validations/sell_more_than_held_rejected
    """
    sec = create_security(symbol="SHRCO", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=100000)
    buy_and_fill(account_id, sec["id"], 2, 5000, order_type="MARKET")  # hold 2 sh
    version = get_account_version(account_id)
    resp = api.create_order(
        F.create_order_payload(account_id, sec["id"], version, side="SELL", order_type="MARKET",
                               quantity=5, is_closing=True),
        _holder(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SHARES, expected_status=409)


def test_insufficient_buying_power_rejected(api):
    """PRD §3.3: "Finally, for a BUY, the required cash to reserve must not exceed the account's
    `buying_power_cents`, else `ERR_INSUFFICIENT_BUYING_POWER`."

    Design: Corner/validations/insufficient_buying_power_rejected
    """
    sec = create_security(symbol="BPCO", last_price_cents=10000, fractional_enabled=True)
    account_id, version = funded_cash_account(amount_cents=10000)  # bp 10000
    resp = api.create_order(
        F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="MARKET",
                               notional_cents=50000),
        _holder(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BUYING_POWER, expected_status=402)


# --------------------------------------------------------------------------
# Endpoint corners
# --------------------------------------------------------------------------
def test_list_deposits_paginated_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned ... Every list response
    carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the
    envelope, where `total_count` is the number of matching records before pagination and
    `has_more` indicates whether records remain beyond the current page."

    Design: Corner/endpoints/list_deposits_paginated_envelope
    """
    acc = create_account(account_type="CASH")
    deposit(acc["id"], 100000, instant_eligible=True)
    deposit(acc["id"], 200000, instant_eligible=False)
    resp = api.list_deposits(acc["id"], _holder(acc["id"]), params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta
    assert len(data) == 1, data
    assert meta["has_more"] is True, meta


def test_cancel_accepted_order_releases_buying_power(api):
    """PRD §3.5: "cancellation moves it from `ACCEPTED` or `PARTIALLY_FILLED` to `CANCELLED`,
    releasing the reserved buying power (the remaining unfilled portion's reservation) back to
    the account and incrementing the account `version`."

    Design: Corner/endpoints/cancel_accepted_order_releases_buying_power
    """
    sec = create_security(symbol="CANCO", last_price_cents=10000, fractional_enabled=True)
    account_id, version = funded_cash_account(amount_cents=100000)  # bp 100000
    order = validate_success(
        api.create_order(
            F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="MARKET",
                                   notional_cents=50000),
            _holder(account_id)),
        expected_status=201,
    )
    # Reservation took bp to 50000.
    mid = get_account(account_id)
    assert mid["buying_power_cents"] == 50000, mid
    cancelled = validate_success(api.cancel_order(order["id"], _holder(account_id)))
    assert cancelled["order_status"] == "CANCELLED", cancelled
    after = get_account(account_id)
    assert after["buying_power_cents"] == 100000, after
