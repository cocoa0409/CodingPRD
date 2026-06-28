"""Composite setup helpers for the regulated sportsbook.

Each test runs against a fresh, empty database (the harness restarts the server
before every test). These helpers build the multi-step preconditions tests need
using only PRD-declared endpoints, threading the entity-backed Bettor identity
(X-User-ID == Account.id) through every ownership-gated call.

All setup calls use get_success_data() so a broken precondition surfaces as a
clear "Setup step failed" error rather than a confusing assertion deep inside a
test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_bettor_headers,
    make_trading_ops_headers,
    make_settlement_agent_headers,
)
from . import factories as f

OPS = TEST_USERS["trading_ops_headers"]
SETTLER = TEST_USERS["settlement_agent_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

DEPOSIT_DEFAULT = 100_000


# ---------------------------------------------------------------------------
# Low-level account helpers
# ---------------------------------------------------------------------------
def register_account(**overrides):
    """POST /accounts → returns the created Account dict (PENDING/ACTIVE)."""
    return get_success_data(api_client.create_account(f.create_account_payload(**overrides), None))


def get_account(account_id, headers=None):
    """GET /accounts/{id} as the owning Bettor (re-reads version, re-evals cooling-off)."""
    hdr = headers or make_bettor_headers(account_id)
    return get_success_data(api_client.get_account(account_id, hdr))


def verify_kyc(account_id, expected_version):
    """ComplianceOfficer VERIFY. Returns the updated Account dict."""
    return get_success_data(api_client.kyc_decision(
        account_id, f.kyc_decision_payload("VERIFY", expected_version), COMPLIANCE))


def deposit(account_id, amount_cents, expected_version):
    """Bettor deposit. Returns the LedgerEntry dict."""
    return get_success_data(api_client.create_deposit(
        account_id, f.deposit_payload(amount_cents, expected_version),
        make_bettor_headers(account_id)))


def submit_geo_check(account_id, detected_state="NJ", accuracy_meters=20, **overrides):
    """Bettor submits a geo reading. Returns the GeoCheck dict."""
    return get_success_data(api_client.create_geo_check(
        account_id, f.geo_check_payload(detected_state, accuracy_meters, **overrides),
        make_bettor_headers(account_id)))


def set_clock(to_iso8601):
    """Advance the logical clock (any operator role may do this)."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def create_promotion(code, **overrides):
    """TradingOps creates a promotion. Returns the Promotion dict."""
    return get_success_data(api_client.create_promotion(f.promotion_payload(code, **overrides), OPS))


# ---------------------------------------------------------------------------
# Tier 1/2: a funded, verified, geo-eligible bettor ready to place bets
# ---------------------------------------------------------------------------
def create_funded_bettor(deposit_cents=DEPOSIT_DEFAULT, geo=True, **acct_overrides):
    """Register → VERIFY KYC → deposit → re-read version → (optional) eligible geo.

    Returns (account_dict, version) where version is the account's CURRENT
    version after the deposit (and is the value a subsequent placement must send
    as expected_account_version).
    """
    acct = register_account(**acct_overrides)
    acct = verify_kyc(acct["id"], acct["version"])
    deposit(acct["id"], deposit_cents, acct["version"])
    acct = get_account(acct["id"])
    if geo:
        submit_geo_check(acct["id"])
    return acct, acct["version"]


def create_verified_bettor(**acct_overrides):
    """Register → VERIFY KYC (no deposit, no geo). Returns (account_dict, version)."""
    acct = register_account(**acct_overrides)
    acct = verify_kyc(acct["id"], acct["version"])
    acct = get_account(acct["id"])
    return acct, acct["version"]


# ---------------------------------------------------------------------------
# Tier 2: the betting board (event → market → selection)
# ---------------------------------------------------------------------------
def create_event(ops_headers=None, **overrides):
    """TradingOps creates an event. Returns the Event dict."""
    return get_success_data(api_client.create_event(f.event_payload(**overrides), ops_headers or OPS))


def create_market(event_id, ops_headers=None, **overrides):
    """TradingOps creates a market on an event. Returns the Market dict."""
    return get_success_data(api_client.create_market(
        event_id, f.market_payload(**overrides), ops_headers or OPS))


def create_selection(market_id, name="AWAY", american_odds=200, ops_headers=None):
    """TradingOps adds a selection. Returns the Selection dict."""
    return get_success_data(api_client.create_selection(
        market_id, f.selection_payload(name, american_odds), ops_headers or OPS))


def create_board(market_type="MONEYLINE", selection_name="AWAY", american_odds=200,
                 liability_cap_cents=90_000_000, line=None, starts_at=None, sport="NBA"):
    """Event(SCHEDULED) + one Market(OPEN) + one Selection(PENDING).

    Returns (event, market, selection).
    """
    ev_kwargs = {"sport": sport}
    if starts_at is not None:
        ev_kwargs["starts_at"] = starts_at
    ev = create_event(**ev_kwargs)
    mkt_kwargs = {"liability_cap_cents": liability_cap_cents}
    if line is not None:
        mkt_kwargs["line"] = line
    mkt = create_market(ev["id"], market_type=market_type, **mkt_kwargs)
    sel = create_selection(mkt["id"], selection_name, american_odds)
    return ev, mkt, sel


# ---------------------------------------------------------------------------
# Tier 3: place a bet (full happy-path placement)
# ---------------------------------------------------------------------------
def place_bet(account_id, bet_type, stake_cents, selection_ids, expected_version, **overrides):
    """Bettor places a bet. Returns the Bet dict (raises on non-2xx)."""
    return get_success_data(api_client.create_bet(
        f.bet_payload(account_id, bet_type, stake_cents, selection_ids, expected_version, **overrides),
        make_bettor_headers(account_id)))


def setup_single_bet(stake_cents=5000, american_odds=200, liability_cap_cents=90_000_000,
                     deposit_cents=DEPOSIT_DEFAULT, market_type="MONEYLINE",
                     selection_name="AWAY", line=None, sport="NBA", bet_overrides=None):
    """Funded bettor + board + one placed SINGLE bet.

    Returns (account, event, market, selection, bet, version_after_placement).
    """
    acct, v = create_funded_bettor(deposit_cents=deposit_cents)
    ev, mkt, sel = create_board(market_type=market_type, selection_name=selection_name,
                                american_odds=american_odds,
                                liability_cap_cents=liability_cap_cents, line=line, sport=sport)
    bet = place_bet(acct["id"], "SINGLE", stake_cents, [sel["id"]], v, **(bet_overrides or {}))
    acct_after = get_account(acct["id"])
    return acct_after, ev, mkt, sel, bet, acct_after["version"]


# ---------------------------------------------------------------------------
# Tier 4/5: settlement helpers
# ---------------------------------------------------------------------------
def take_event_live(event_id, ops_headers=None):
    """TradingOps moves an event SCHEDULED → LIVE (suspends its open markets)."""
    return get_success_data(api_client.set_event_status(event_id, {"to": "LIVE"}, ops_headers or OPS))


def void_event(event_id, ops_headers=None):
    """TradingOps voids an event (cascade voids markets/selections/placed bets)."""
    return get_success_data(api_client.set_event_status(event_id, {"to": "VOIDED"}, ops_headers or OPS))


def settle_event(event_id, home_score, away_score, settler_headers=None):
    """SettlementAgent posts the official result → SETTLED + grading cascade.

    Uses a distinct opaque agent id from the default TradingOps id so the
    segregation-of-duties check passes for boards built with the default OPS
    headers.
    """
    return get_success_data(api_client.post_event_result(
        event_id, {"home_score": home_score, "away_score": away_score},
        settler_headers or SETTLER))


def claim_bonus(account_id, promotion_id, expected_version):
    """Bettor claims a promotion. Returns the BonusGrant dict."""
    return get_success_data(api_client.claim_bonus(
        account_id, f.bonus_claim_payload(promotion_id, expected_version),
        make_bettor_headers(account_id)))


def set_rg_control(account_id, control_type, expected_version, headers=None, **overrides):
    """Create an RG control. Defaults to the owning Bettor's identity; pass
    COMPLIANCE explicitly for SELF_EXCLUSION. Returns the RGControl dict."""
    hdr = headers or make_bettor_headers(account_id)
    return get_success_data(api_client.create_rg_control(
        account_id, f.rg_control_payload(control_type, expected_version, **overrides), hdr))
