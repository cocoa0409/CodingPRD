"""Composite setup helpers — encapsulate the multi-step preambles the test
recipes share, so tests focus on assertions, not plumbing.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server with an empty DB before each test).
Setup calls use get_success_data() (lenient) so setup failures surface clearly.

Identity threading: after creating an Account, every ownership-gated Trader call
uses make_trader_headers(account["id"]) — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_trader_headers, make_operator_headers, make_compliance_headers,
)
from . import factories as f


OP = TEST_USERS["operator_headers"]


# ---------------------------------------------------------------------------
# Clock + asset/fee config
# ---------------------------------------------------------------------------
def set_clock(iso8601):
    """Set the ledger clock (PRD §2.4)."""
    return get_success_data(api_client.set_clock(iso8601, OP))


def create_asset(**overrides):
    """Create an arbitrary asset; returns the AssetConfig dict."""
    payload = f.create_asset_payload(**overrides)
    return get_success_data(api_client.create_asset(payload, OP))


def create_usd_asset(**overrides):
    return get_success_data(api_client.create_asset(f.usd_asset_payload(**overrides), OP))


def create_btc_asset(**overrides):
    return get_success_data(api_client.create_asset(f.btc_asset_payload(**overrides), OP))


def create_eth_asset(**overrides):
    return get_success_data(api_client.create_asset(f.eth_asset_payload(**overrides), OP))


def create_tier_base_fee_schedule(**overrides):
    return get_success_data(
        api_client.create_fee_schedule(f.tier_base_fee_schedule_payload(**overrides), OP)
    )


def create_usd_btc_with_fees():
    """Create USD (fiat), BTC, and a TIER_BASE fee schedule (10/30 bps).
    Returns (usd, btc, fee_schedule)."""
    usd = create_usd_asset()
    btc = create_btc_asset()
    fee = create_tier_base_fee_schedule()
    return usd, btc, fee


# ---------------------------------------------------------------------------
# Accounts + KYC tier progression (PRD §3.1)
# ---------------------------------------------------------------------------
def create_account(email="trader@example.com", full_name="Test Trader",
                   residence_country="US", cost_basis_method=None):
    payload = f.create_account_payload(
        email=email, full_name=full_name, residence_country=residence_country
    )
    if cost_basis_method is not None:
        payload["cost_basis_method"] = cost_basis_method
    return get_success_data(api_client.create_account(payload))


def upgrade_one_tier(account_id, requested_tier):
    """Apply for `requested_tier` (Trader) then Operator-approve. Returns the
    updated account. Walks one KYC step (PRD §3.1)."""
    trader = make_trader_headers(account_id)
    get_success_data(api_client.create_kyc_application(
        account_id, f.kyc_application_payload(requested_tier), trader
    ))
    return get_success_data(api_client.create_kyc_decision(
        account_id, f.kyc_decision_payload("APPROVE"), OP
    ))


def create_account_at_tier(tier, email="trader@example.com", full_name="Test Trader",
                           residence_country="US", cost_basis_method=None):
    """Create an account and walk it up to `tier` ('TIER_1'/'TIER_2'/'TIER_3')
    one approved step at a time. Returns the account dict (latest snapshot)."""
    acc = create_account(email, full_name, residence_country, cost_basis_method)
    acc_id = acc["id"]
    order = ["TIER_0", "TIER_1", "TIER_2", "TIER_3"]
    target_idx = order.index(tier)
    latest = acc
    for i in range(1, target_idx + 1):
        latest = upgrade_one_tier(acc_id, order[i])
    return latest


def get_account_version(account_id, headers=None):
    """Read the account's current version (for OCC tokens)."""
    h = headers or make_trader_headers(account_id)
    return get_success_data(api_client.get_account(account_id, h))["version"]


# ---------------------------------------------------------------------------
# Deposits + crediting (PRD §3.4)
# ---------------------------------------------------------------------------
def create_and_credit_deposit(account_id, asset, amount, unit_cost_usd,
                              required_confirmations=1):
    """Create a deposit and advance it to CREDITED.

    Per PRD §3.4 a non-fiat deposit always passes through CONFIRMING: the first
    advance from DETECTED moves it DETECTED -> CONFIRMING (crediting held only,
    regardless of delta), and a *subsequent* advance that brings the running
    count to at least `required_confirmations` moves it CONFIRMING -> CREDITED.
    So crediting a non-fiat deposit takes two advances: one to enter CONFIRMING,
    then one that reaches the threshold. Returns the credited deposit dict."""
    dep = get_success_data(api_client.create_deposit(
        f.create_deposit_payload(account_id, asset, amount, unit_cost_usd), OP
    ))
    # First advance: DETECTED -> CONFIRMING (credits held; confirmations += 1).
    get_success_data(api_client.advance_confirmations(
        dep["id"], f.confirmations_payload(1), OP
    ))
    # Second advance: bring the running count to at least required_confirmations
    # so the deposit crosses CONFIRMING -> CREDITED (held -> available + lot).
    get_success_data(api_client.advance_confirmations(
        dep["id"], f.confirmations_payload(required_confirmations), OP
    ))
    return get_success_data(api_client.get_deposit(dep["id"], OP))


def credit_fiat(account_id, asset, amount, unit_cost_usd=1):
    """Credit a fiat deposit (instant credit via a single delta=0 confirmation)."""
    dep = get_success_data(api_client.create_deposit(
        f.create_deposit_payload(account_id, asset, amount, unit_cost_usd), OP
    ))
    get_success_data(api_client.advance_confirmations(
        dep["id"], f.confirmations_payload(0), OP
    ))
    return get_success_data(api_client.get_deposit(dep["id"], OP))


# ---------------------------------------------------------------------------
# Withdrawal addresses (PRD §3.5)
# ---------------------------------------------------------------------------
def add_withdrawal_address(account_id, asset, chain_address="0xDEST", label="out"):
    """Add a PENDING_HOLD whitelist address using the current account version.
    Returns the address dict."""
    trader = make_trader_headers(account_id)
    version = get_account_version(account_id, trader)
    payload = f.create_withdrawal_address_payload(
        account_id, asset, chain_address, label, version
    )
    return get_success_data(api_client.create_withdrawal_address(payload, trader))


def add_and_activate_address(account_id, asset, chain_address="0xDEST", label="out",
                             activate_clock=None):
    """Add a whitelist address; if activate_clock is given, set the clock there
    (past the 24h hold) and activate it to ACTIVE. Returns the address dict."""
    trader = make_trader_headers(account_id)
    addr = add_withdrawal_address(account_id, asset, chain_address, label)
    if activate_clock is not None:
        set_clock(activate_clock)
    return get_success_data(
        api_client.activate_withdrawal_address(addr["id"], trader)
    )


# ---------------------------------------------------------------------------
# Orders (PRD §3.8)
# ---------------------------------------------------------------------------
def place_order(account_id, base_asset, quote_asset, side, order_type, quantity,
                limit_price=None, time_in_force=None):
    """Place an order with a freshly-read OCC token. Returns the order dict."""
    trader = make_trader_headers(account_id)
    version = get_account_version(account_id, trader)
    payload = f.create_order_payload(
        account_id, base_asset, quote_asset, side, order_type, quantity,
        version, limit_price=limit_price, time_in_force=time_in_force
    )
    return get_success_data(api_client.create_order(payload, trader))


def rest_sell_limit(account_id, base_asset, quote_asset, quantity, limit_price):
    """Place a resting SELL LIMIT (GTC) order. Returns the maker order dict."""
    return place_order(
        account_id, base_asset, quote_asset, "SELL", "LIMIT", quantity,
        limit_price=limit_price, time_in_force="GTC"
    )


def rest_buy_limit(account_id, base_asset, quote_asset, quantity, limit_price):
    """Place a resting BUY LIMIT (GTC) order. Returns the order dict."""
    return place_order(
        account_id, base_asset, quote_asset, "BUY", "LIMIT", quantity,
        limit_price=limit_price, time_in_force="GTC"
    )


# ---------------------------------------------------------------------------
# Higher-level composite scenarios
# ---------------------------------------------------------------------------
def setup_seller_with_resting_btc_ask(clock="2026-02-01T00:00:00Z",
                                      sell_qty=1.0, sell_price=40000,
                                      seller_btc=1.0):
    """USD/BTC + TIER_BASE fees; a TIER_1 seller holding `seller_btc` BTC that
    rests a SELL LIMIT `sell_qty` BTC @ `sell_price`. Returns
    (seller_account, maker_order). Used by trade/fee/cascade recipes."""
    set_clock(clock)
    create_usd_btc_with_fees()
    seller = create_account_at_tier("TIER_1", email="seller@x.com", full_name="Seller")
    create_and_credit_deposit(seller["id"], "BTC", seller_btc, 35000,
                              required_confirmations=1)
    maker = rest_sell_limit(seller["id"], "BTC", "USD", sell_qty, sell_price)
    return seller, maker


def setup_buyer_with_usd(clock=None, usd=50000, email="buyer@x.com",
                         full_name="Buyer"):
    """A TIER_1 buyer account holding `usd` USD available. Assumes USD asset
    already exists. Returns the buyer account dict."""
    if clock is not None:
        set_clock(clock)
    buyer = create_account_at_tier("TIER_1", email=email, full_name=full_name)
    credit_fiat(buyer["id"], "USD", usd)
    return buyer


def setup_trade_match_scenario(clock="2026-07-01T00:00:00Z", sell_price=40000,
                               buyer_usd=50000):
    """Full cross-account scenario: resting SELL LIMIT 1.0 BTC @ sell_price from a
    TIER_1 seller, plus a TIER_1 buyer holding buyer_usd USD ready to send a
    MARKET BUY. Returns (seller, maker_order, buyer)."""
    seller, maker = setup_seller_with_resting_btc_ask(
        clock=clock, sell_qty=1.0, sell_price=sell_price, seller_btc=1.0
    )
    buyer = setup_buyer_with_usd(usd=buyer_usd)
    return seller, maker, buyer


def setup_account_with_credited_asset(tier, asset_payload_fn, account_kwargs=None,
                                      amount=1.0, unit_cost_usd=30000,
                                      required_confirmations=1,
                                      clock="2026-12-01T00:00:00Z"):
    """Generic: clock + one asset + a KYC-`tier` account credited `amount` of the
    asset. Returns (account, asset). asset_payload_fn is one of the asset helpers
    in this module (e.g. create_btc_asset)."""
    set_clock(clock)
    asset = asset_payload_fn()
    account_kwargs = account_kwargs or {}
    acc = create_account_at_tier(tier, **account_kwargs)
    create_and_credit_deposit(acc["id"], asset["symbol"], amount, unit_cost_usd,
                              required_confirmations=required_confirmations)
    return acc, asset


def submit_withdrawal(account_id, address_id, amount, replaces_withdrawal_id=None):
    """Submit a withdrawal (Trader). Returns the withdrawal dict."""
    trader = make_trader_headers(account_id)
    payload = f.create_withdrawal_payload(account_id, address_id, amount)
    if replaces_withdrawal_id is not None:
        payload["replaces_withdrawal_id"] = replaces_withdrawal_id
    return get_success_data(api_client.create_withdrawal(payload, trader))


def screen_to(withdrawal_id, officer_user_id="co-1"):
    """Move a SUBMITTED withdrawal to SCREENING under officer_user_id."""
    co = make_compliance_headers(officer_user_id)
    return get_success_data(api_client.screen_withdrawal(withdrawal_id, co))


def screen_result(withdrawal_id, result, officer_user_id="co-1"):
    """Resolve screening with CLEAR/HOLD/REJECT under officer_user_id."""
    co = make_compliance_headers(officer_user_id)
    return get_success_data(
        api_client.screen_result(withdrawal_id, f.screen_result_payload(result), co)
    )


def withdraw_to_broadcast(account_id, address_id, amount, officer_user_id="co-1"):
    """Full lifecycle of a non-travel-rule withdrawal:
    submit -> screen -> CLEAR -> APPROVED -> broadcast -> BROADCAST.
    Returns the withdrawal dict after broadcast. Triggers the cost-basis disposal."""
    wd = submit_withdrawal(account_id, address_id, amount)
    screen_to(wd["id"], officer_user_id)
    screen_result(wd["id"], "CLEAR", officer_user_id)
    return get_success_data(api_client.broadcast_withdrawal(wd["id"], OP))


def setup_account_with_two_eth_lots(cost_basis_method, email, full_name,
                                    base_clock="2026-01-01T00:00:00Z"):
    """A TIER_2 account (chosen cost_basis_method) holding two CREDITED ETH lots:
    1.0 @ 1500 (acquired first) and 1.0 @ 2500 (acquired later), plus one ACTIVE
    ETH whitelist address. Assumes the ETH asset already exists.
    Sets the clock through several days. Returns (account, address).
    """
    acc = create_account_at_tier(
        "TIER_2", email=email, full_name=full_name, cost_basis_method=cost_basis_method
    )
    acc_id = acc["id"]
    # older lot 1.0 @ 1500
    set_clock(base_clock)
    create_and_credit_deposit(acc_id, "ETH", 1.0, 1500, required_confirmations=2)
    # newer lot 1.0 @ 2500, one day later
    set_clock("2026-01-02T00:00:00Z")
    create_and_credit_deposit(acc_id, "ETH", 1.0, 2500, required_confirmations=2)
    # add whitelist address (before the activation clock so the 24h hold elapses)
    addr = add_withdrawal_address(acc_id, "ETH", chain_address="0x" + full_name[:4],
                                  label="out")
    set_clock("2026-01-03T00:00:00Z")
    addr = get_success_data(
        api_client.activate_withdrawal_address(addr["id"], make_trader_headers(acc_id))
    )
    return acc, addr


def setup_staking_position(account_id, asset, principal_amount, apr_bps):
    """Open an ACTIVE staking position. Returns the position dict."""
    trader = make_trader_headers(account_id)
    payload = f.create_staking_position_payload(
        account_id, asset, principal_amount, apr_bps
    )
    return get_success_data(api_client.create_staking_position(payload, trader))
