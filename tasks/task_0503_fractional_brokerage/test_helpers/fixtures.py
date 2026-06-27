"""Composite setup helpers.

These encapsulate the multi-step preambles that the difficulty- and
corner-design recipes share: register a security, open and fund an account,
read the OCC version, place a BUY order, report a fill, advance the clock,
discover the position, etc. They use get_success_data() (lenient) internally
so a setup misstep surfaces as a clear "Setup failed" rather than a confusing
assertion error.

Identity threading: AccountHolder is entity-backed, so every ownership-gated
call uses make_account_holder_headers(account["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_account_holder_headers,
)
from . import factories as F
from .constants import INSTANT_CAP_CENTS


# --------------------------------------------------------------------------
# Header shortcuts
# --------------------------------------------------------------------------
def _clearing():
    return TEST_USERS["clearing_system_headers"]


def _compliance():
    return TEST_USERS["compliance_officer_headers"]


def _market_data():
    return TEST_USERS["market_data_headers"]


def _holder(account_id):
    return make_account_holder_headers(account_id)


# --------------------------------------------------------------------------
# Tier 0: atomic builders
# --------------------------------------------------------------------------
def create_security(symbol=None, instrument_type="EQUITY", last_price_cents=10000,
                    fractional_enabled=True, **overrides):
    """Register a tradable instrument. Returns the Security resource."""
    payload = F.create_security_payload(
        instrument_type=instrument_type,
        last_price_cents=last_price_cents,
        fractional_enabled=fractional_enabled,
        **overrides,
    )
    if symbol is not None:
        payload["symbol"] = symbol
    resp = api_client.create_security(payload, _clearing())
    return get_success_data(resp)


def create_account(account_type="CASH", holder_email=None):
    """Open a brokerage account. Returns the Account resource."""
    payload = F.create_account_payload(account_type=account_type)
    if holder_email is not None:
        payload["holder_email"] = holder_email
    resp = api_client.create_account(payload, TEST_USERS["account_holder_headers"])
    return get_success_data(resp)


def get_account(account_id):
    """Fetch the live account (computed equity / buying_power / version)."""
    resp = api_client.get_account(account_id, _holder(account_id))
    return get_success_data(resp)


def get_account_version(account_id):
    """Return the account's current OCC version integer."""
    return get_account(account_id)["version"]


def deposit(account_id, amount_cents, instant_eligible=True):
    """Record an instant deposit. Returns the Deposit resource."""
    payload = F.create_deposit_payload(amount_cents=amount_cents, instant_eligible=instant_eligible)
    resp = api_client.create_deposit(account_id, payload, _holder(account_id))
    return get_success_data(resp)


def advance_clock(to_iso8601):
    """Advance the logical clock and run the settlement sweep."""
    payload = F.advance_clock_payload(to_iso8601)
    return api_client.advance_clock(payload, _clearing())


def update_quote(security_id, last_price_cents):
    """Push a fresh quote (MarketData)."""
    payload = F.quote_payload(last_price_cents)
    resp = api_client.update_quote(security_id, payload, _market_data())
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 1: funded accounts (instant cash buying power) — CASH and MARGIN
# --------------------------------------------------------------------------
def funded_cash_account(amount_cents=100000):
    """Open a CASH account and grant `amount_cents` of spendable buying power.

    Instant provisional credit is capped at INSTANT_CAP_CENTS per account
    (PRD §3.1), so an instant-eligible deposit larger than that ceiling would be
    rejected with ERR_INSTANT_LIMIT_EXCEEDED. When `amount_cents` exceeds the
    cap, fund instead with a non-instant deposit and advance the logical clock so
    it settles into real settled cash (T+1 = 2026-01-02). For amounts at or below
    the cap, use the instant path so the buying power is visible immediately.

    Returns (account_id, version) where version is the account's version AFTER the
    funding is complete (ready to feed an order's expected_account_version).
    """
    acc = create_account(account_type="CASH")
    if amount_cents <= INSTANT_CAP_CENTS:
        deposit(acc["id"], amount_cents, instant_eligible=True)
    else:
        # Non-instant deposit settles T+1; advance the clock to settle it. The
        # clock moves only to 2026-01-02, well before any dividend ex_date used
        # by the fixtures, so dividend windows are unaffected.
        deposit(acc["id"], amount_cents, instant_eligible=False)
        advance_clock("2026-01-02T00:00:00Z")
    return acc["id"], get_account_version(acc["id"])


def settled_margin_account(amount_cents=500000, settle_to="2026-01-05T00:00:00Z"):
    """Open a MARGIN account, deposit (non-instant), advance the clock so the
    deposit settles. Returns (account_id, current_version).
    """
    acc = create_account(account_type="MARGIN")
    deposit(acc["id"], amount_cents, instant_eligible=False)
    advance_clock(settle_to)
    return acc["id"], get_account_version(acc["id"])


# --------------------------------------------------------------------------
# Tier 2: place + (optionally) fill an order
# --------------------------------------------------------------------------
def place_order(account_id, security_id, expected_account_version, **overrides):
    """Place an order with the supplied OCC version. Returns the Order resource
    (which may be REJECTED — caller inspects). Raises on non-2xx."""
    payload = F.create_order_payload(account_id, security_id, expected_account_version, **overrides)
    resp = api_client.create_order(payload, _holder(account_id))
    return get_success_data(resp)


def fill_order(order_id, fill_quantity, fill_price_cents):
    """Report a full/partial execution against an order. Returns the Fill."""
    payload = F.create_fill_payload(fill_quantity, fill_price_cents)
    resp = api_client.create_fill(order_id, payload, _clearing())
    return get_success_data(resp)


def buy_and_fill(account_id, security_id, quantity, fill_price_cents,
                 order_type="MARKET", limit_price_cents=None):
    """Place a BUY for `quantity` shares (auto-reading the OCC version) and
    immediately report a single full fill at `fill_price_cents`.
    Returns (order, fill).
    """
    version = get_account_version(account_id)
    overrides = {"side": "BUY", "order_type": order_type, "quantity": quantity}
    if limit_price_cents is not None:
        overrides["limit_price_cents"] = limit_price_cents
    order = place_order(account_id, security_id, version, **overrides)
    fill = fill_order(order["id"], quantity, fill_price_cents)
    return order, fill


def sell_and_fill(account_id, security_id, quantity, fill_price_cents,
                  order_type="MARKET", limit_price_cents=None, is_closing=True):
    """Place a closing SELL for `quantity` shares and report a full fill.
    Returns (order, fill).
    """
    version = get_account_version(account_id)
    overrides = {"side": "SELL", "order_type": order_type, "quantity": quantity, "is_closing": is_closing}
    if limit_price_cents is not None:
        overrides["limit_price_cents"] = limit_price_cents
    order = place_order(account_id, security_id, version, **overrides)
    fill = fill_order(order["id"], quantity, fill_price_cents)
    return order, fill


# --------------------------------------------------------------------------
# Tier 3: positions / lots
# --------------------------------------------------------------------------
def get_first_position(account_id):
    """Return the account's first Position resource (after at least one BUY)."""
    data = get_success_data(
        api_client.list_positions(_holder(account_id), params={"account_id": account_id})
    )
    return data[0]


def position_with_lots(account_id, security_id, lots):
    """Build a CASH account position by executing a sequence of BUY fills.

    `lots` is a list of (quantity, fill_price_cents) tuples, executed in order
    so the FIFO acquisition order matches the list order. Returns the Position
    resource after all buys.
    """
    for qty, price in lots:
        buy_and_fill(account_id, security_id, qty, price, order_type="MARKET")
    return get_first_position(account_id)


# --------------------------------------------------------------------------
# Tier 4: MARGIN account driven into a deficiency posture by a quote drop
# --------------------------------------------------------------------------
def margin_account_holding(symbol, shares=100, fill_price_cents=10000,
                          maintenance_rate_bps=2500, deposit_cents=500000):
    """Open a settled MARGIN account holding `shares` of a freshly-registered
    non-fractional security via a LIMIT BUY fully filled at `fill_price_cents`.

    Returns (account_id, security_id) with the account in ACTIVE posture.
    """
    sec = create_security(
        symbol=symbol,
        instrument_type="EQUITY",
        last_price_cents=fill_price_cents,
        fractional_enabled=False,
        maintenance_rate_bps=maintenance_rate_bps,
    )
    account_id, version = settled_margin_account(amount_cents=deposit_cents)
    order = place_order(
        account_id, sec["id"], version,
        side="BUY", order_type="LIMIT", quantity=shares, limit_price_cents=fill_price_cents,
    )
    fill_order(order["id"], shares, fill_price_cents)
    return account_id, sec["id"]


def margin_account_in_deficiency(symbol, shares=100, original_price_cents=10000,
                                 dropped_price_cents=4000, maintenance_rate_bps=2500,
                                 deposit_cents=500000):
    """Build a MARGIN account holding `shares`, then push a quote drop that
    drives maintenance_excess below zero (RESTRICTED_CLOSING_ONLY posture).

    Returns (account_id, security_id) with the quote already at the dropped price.
    """
    account_id, security_id = margin_account_holding(
        symbol, shares=shares, fill_price_cents=original_price_cents,
        maintenance_rate_bps=maintenance_rate_bps, deposit_cents=deposit_cents,
    )
    update_quote(security_id, dropped_price_cents)
    return account_id, security_id


def margin_account_with_issued_call(symbol, shares=100, original_price_cents=10000,
                                    dropped_price_cents=4000, maintenance_rate_bps=2500,
                                    deposit_cents=500000):
    """Drive a MARGIN account into deficiency and issue a MarginCall.

    Returns (account_id, security_id, margin_call) with the call ISSUED.
    """
    account_id, security_id = margin_account_in_deficiency(
        symbol, shares=shares, original_price_cents=original_price_cents,
        dropped_price_cents=dropped_price_cents, maintenance_rate_bps=maintenance_rate_bps,
        deposit_cents=deposit_cents,
    )
    resp = api_client.issue_margin_call(account_id, _clearing())
    return account_id, security_id, get_success_data(resp)


# --------------------------------------------------------------------------
# Tier 5: positions with a paid dividend (DRIP on/off)
# --------------------------------------------------------------------------
def position_with_paid_dividend(symbol, shares, rate_per_share_cents, ex_date,
                                last_price_cents=10000, drip_enabled=False,
                                deposit_cents=None):
    """Open a CASH account, buy `shares`, optionally enable DRIP, then announce
    and pay a dividend on the resulting position.

    Returns (account_id, security_id, position, dividend) with the dividend PAID.
    """
    if deposit_cents is None:
        deposit_cents = max(shares * last_price_cents + 100000, 200000)
    sec = create_security(symbol=symbol, last_price_cents=last_price_cents, fractional_enabled=True)
    account_id, _version = funded_cash_account(amount_cents=deposit_cents)
    buy_and_fill(account_id, sec["id"], shares, last_price_cents, order_type="MARKET")
    position = get_first_position(account_id)
    if drip_enabled:
        api_client.set_drip(position["id"], F.drip_payload(True), _holder(account_id))
        # Re-fetch so the returned snapshot reflects drip_enabled=True (the toggle
        # is a mutation; the pre-toggle snapshot still shows the default False).
        position = get_first_position(account_id)
    div_payload = F.create_dividend_payload(account_id, position["id"], rate_per_share_cents, ex_date)
    div = get_success_data(api_client.create_dividend(div_payload, _clearing()))
    paid = get_success_data(api_client.pay_dividend(div["id"], _clearing()))
    return account_id, sec["id"], position, paid


def announced_dividend(symbol, shares, rate_per_share_cents, ex_date,
                       last_price_cents=10000, deposit_cents=200000):
    """Open a CASH account holding `shares` and announce (but not pay) a
    dividend. Returns (account_id, security_id, position, dividend).
    """
    sec = create_security(symbol=symbol, last_price_cents=last_price_cents, fractional_enabled=True)
    account_id, _version = funded_cash_account(amount_cents=deposit_cents)
    buy_and_fill(account_id, sec["id"], shares, last_price_cents, order_type="MARKET")
    position = get_first_position(account_id)
    div_payload = F.create_dividend_payload(account_id, position["id"], rate_per_share_cents, ex_date)
    div = get_success_data(api_client.create_dividend(div_payload, _clearing()))
    return account_id, sec["id"], position, div


# --------------------------------------------------------------------------
# Tier 6: options approval lifecycle
# --------------------------------------------------------------------------
def submitted_options_approval(account_id, requested_level, stated_experience_years,
                               liquid_net_worth_cents):
    """Submit an options application for an existing account. Returns the
    OptionsApproval resource (status SUBMITTED)."""
    payload = F.create_options_approval_payload(
        account_id, requested_level, stated_experience_years, liquid_net_worth_cents
    )
    resp = api_client.create_options_approval(payload, _holder(account_id))
    return get_success_data(resp)


def approved_options_account(requested_level=2, stated_experience_years=3,
                             liquid_net_worth_cents=5000000):
    """Open a CASH account and drive an options approval to APPROVED.

    Returns (account_id, approval) with the account's options_level raised.
    """
    acc = create_account(account_type="CASH")
    approval = submitted_options_approval(
        acc["id"], requested_level, stated_experience_years, liquid_net_worth_cents
    )
    version = get_account_version(acc["id"])
    decided = get_success_data(api_client.decide_options_approval(
        approval["id"], F.decide_options_approval_payload("APPROVE", version), _compliance()
    ))
    return acc["id"], decided
