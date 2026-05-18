"""Composite setup helpers — multi-step preambles tests can reuse.

Many tests require the system in a late state (e.g., an Account
funded, with an ACTIVE Client, an open Lot, a settled SELL, etc.).
Each fixture composes the lower-level steps so the test body can focus
on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

- ComplianceOfficer / TaxAdmin / system are OPAQUE; shared constants
  (compliance_officer_headers, tax_admin_headers, system_headers) are
  canonical.
- ClientUser is ENTITY-BACKED. Every ClientUser-driven call whose
  success depends on owning the targeted resource MUST mint headers
  via make_client_user_headers(client["id"]). The fixtures here
  return the actual Client row so consumer tests can route
  ClientUser-acting calls through make_client_user_headers.

Setup calls use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as 'Setup failed' rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AGE_BIAS_THRESHOLD,
    ASSET_CLASSES,
    DRIFT_TRIGGER_PCT,
    MIN_HARVEST_THRESHOLD_CENTS,
    TEST_DEFAULTS,
)
from .factories import (
    cash_deposit_payload,
    clock_advance_payload,
    create_account_payload,
    create_client_payload,
    create_correlation_link_payload,
    create_form_1099b_payload,
    create_model_portfolio_payload,
    create_questionnaire_payload,
    create_security_payload,
    create_trade_payload,
    iso_instant_utc,
    quarter_key_of,
    random_group_id,
    random_ticker,
    record_dividend_payload,
    set_pricing_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_user_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.12 (system role)
# ===========================================================================
def advance_clock_to(
    to_iso: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §3.12: system-only."""
    headers = headers or TEST_USERS["system_headers"]
    resp = api_client.advance_clock(
        clock_advance_payload(to_iso=to_iso), headers,
    )
    return get_success_data(resp)


def advance_clock_tick(
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.12: 'when omitted, the clock advances by one tick'."""
    headers = headers or TEST_USERS["system_headers"]
    resp = api_client.advance_clock({}, headers)
    return get_success_data(resp)


# ===========================================================================
# Clients — PRD §3.1
# ===========================================================================
def create_client(
    *,
    full_name: Optional[str] = None,
    birth_date: Optional[str] = None,
    time_horizon_years: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /clients — PRD §3.1 (ComplianceOfficer)."""
    headers = headers or TEST_USERS["compliance_officer_headers"]
    payload = create_client_payload(
        full_name=full_name,
        birth_date=birth_date,
        time_horizon_years=time_horizon_years,
        **overrides,
    )
    resp = api_client.create_client(payload, headers)
    return get_success_data(resp)


def submit_questionnaire(
    client: Dict[str, Any],
    *,
    q1_loss_tolerance: int = 3,
    q2_volatility_comfort: int = 3,
    q3_growth_vs_stability: int = 3,
    q4_liquidity_need: int = 3,
    q5_experience: int = 3,
    scoring_method: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """PRD §3.1: 'A ClientUser may submit their own questionnaire only
    when the path's clientId equals their X-User-ID; a
    ComplianceOfficer may submit on the client's behalf.'

    Default actor is ComplianceOfficer (opaque) so ownership is not
    exercised on setup. To exercise ClientUser ownership, pass
    headers=make_client_user_headers(client["id"]).
    """
    headers = headers or TEST_USERS["compliance_officer_headers"]
    payload = create_questionnaire_payload(
        q1_loss_tolerance=q1_loss_tolerance,
        q2_volatility_comfort=q2_volatility_comfort,
        q3_growth_vs_stability=q3_growth_vs_stability,
        q4_liquidity_need=q4_liquidity_need,
        q5_experience=q5_experience,
        scoring_method=scoring_method,
    )
    resp = api_client.submit_questionnaire(
        client["id"], payload, headers,
    )
    return get_success_data(resp)


def activate_client(client: Dict[str, Any],
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.activate_client(client["id"], headers)
    return get_success_data(resp)


def suspend_client(client: Dict[str, Any],
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.suspend_client(client["id"], headers)
    return get_success_data(resp)


def reinstate_client(client: Dict[str, Any],
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.reinstate_client(client["id"], headers)
    return get_success_data(resp)


def re_get_client(client_id: str,
                  headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.get_client(client_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Model portfolios — PRD §3.2
# ===========================================================================
def create_model_portfolio(
    *,
    risk_band: str = "MODERATE",
    horizon_band: str = "MID",
    target_allocation: Optional[Dict[str, float]] = None,
    is_active: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """POST /model-portfolios — PRD §3.2 (Advisor)."""
    headers = headers or TEST_USERS["advisor_headers"]
    payload = create_model_portfolio_payload(
        risk_band=risk_band, horizon_band=horizon_band,
        target_allocation=target_allocation, is_active=is_active,
    )
    resp = api_client.create_model_portfolio(payload, headers)
    return get_success_data(resp)


def seed_nine_model_portfolios(
    target_allocations: Optional[Dict[Tuple[str, str], Dict[str, float]]] = None,
) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Seed 9 active ModelPortfolio rows covering every (risk_band,
    horizon_band) combination — required for the
    model_portfolio_tiered_3x3_matrix difficulty instance.

    Returns a mapping (risk_band, horizon_band) -> ModelPortfolio row.
    """
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    target_allocations = target_allocations or {}
    for rb in ("CONSERVATIVE", "MODERATE", "AGGRESSIVE"):
        for hb in ("SHORT", "MID", "LONG"):
            alloc = target_allocations.get(
                (rb, hb), TEST_DEFAULTS["MODEL_ALLOCATION"],
            )
            mp = create_model_portfolio(
                risk_band=rb, horizon_band=hb,
                target_allocation=dict(alloc),
            )
            out[(rb, hb)] = mp
    return out


# ===========================================================================
# Securities / pricing / correlation — PRD §3.9
# ===========================================================================
def create_security(
    *,
    ticker: Optional[str] = None,
    asset_class: str = "US_EQUITY",
    substantially_identical_group_id: Optional[str] = None,
    is_investable: Optional[bool] = None,
    last_price_cents: int = TEST_DEFAULTS["SECURITY_PRICE_CENTS"],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    payload = create_security_payload(
        ticker=ticker, asset_class=asset_class,
        substantially_identical_group_id=(
            substantially_identical_group_id
        ),
        is_investable=is_investable,
        last_price_cents=last_price_cents,
    )
    resp = api_client.create_security(payload, headers)
    return get_success_data(resp)


def set_pricing(security: Dict[str, Any], last_price_cents: int,
                headers: Optional[Dict[str, str]] = None,
                ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    payload = set_pricing_payload(security["id"], last_price_cents)
    resp = api_client.set_pricing(payload, headers)
    return get_success_data(resp)


def create_correlation_link(
    security_a: Dict[str, Any],
    security_b: Dict[str, Any],
    correlation: float = 0.95,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    payload = create_correlation_link_payload(
        security_a_id=security_a["id"],
        security_b_id=security_b["id"],
        correlation=correlation,
    )
    resp = api_client.create_correlation_link(payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Accounts — PRD §3.3
# ===========================================================================
def create_account(client: Dict[str, Any],
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    payload = create_account_payload(client_id=client["id"])
    resp = api_client.create_account(payload, headers)
    return get_success_data(resp)


def fund_account(account: Dict[str, Any], amount_cents: int,
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    payload = cash_deposit_payload(amount_cents=amount_cents)
    resp = api_client.cash_deposit(account["id"], payload, headers)
    return get_success_data(resp)


def freeze_account(account: Dict[str, Any],
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.freeze_account(account["id"], headers)
    return get_success_data(resp)


def unfreeze_account(account: Dict[str, Any],
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.unfreeze_account(account["id"], headers)
    return get_success_data(resp)


def re_get_account(account_id: str,
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["compliance_officer_headers"]
    resp = api_client.get_account(account_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Trades — PRD §3.4
# ===========================================================================
def create_trade(
    account: Dict[str, Any],
    security: Dict[str, Any],
    *,
    side: str,
    requested_shares: float,
    cost_basis_method: Optional[str] = None,
    specific_lot_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    payload = create_trade_payload(
        security_id=security["id"], side=side,
        requested_shares=requested_shares,
        cost_basis_method=cost_basis_method,
        specific_lot_id=specific_lot_id,
    )
    resp = api_client.create_trade(account["id"], payload, headers)
    return get_success_data(resp)


def execute_trade(account: Dict[str, Any], trade: Dict[str, Any],
                  headers: Optional[Dict[str, str]] = None,
                  ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    resp = api_client.execute_trade(account["id"], trade["id"], headers)
    return get_success_data(resp)


def settle_trade(account: Dict[str, Any], trade: Dict[str, Any],
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    resp = api_client.settle_trade(account["id"], trade["id"], headers)
    return get_success_data(resp)


def execute_and_settle(account: Dict[str, Any],
                       trade: Dict[str, Any],
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    execute_trade(account, trade, headers)
    return settle_trade(account, trade, headers)


def buy_and_settle(
    account: Dict[str, Any],
    security: Dict[str, Any],
    shares: float,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create BUY -> execute -> settle on the account. Returns the
    settled BUY trade."""
    trade = create_trade(
        account, security,
        side="BUY", requested_shares=shares,
        headers=headers,
    )
    execute_trade(account, trade, headers)
    settled = settle_trade(account, trade, headers)
    return settled


def sell_and_settle(
    account: Dict[str, Any],
    security: Dict[str, Any],
    shares: float,
    *,
    cost_basis_method: Optional[str] = None,
    specific_lot_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    trade = create_trade(
        account, security,
        side="SELL", requested_shares=shares,
        cost_basis_method=cost_basis_method,
        specific_lot_id=specific_lot_id,
        headers=headers,
    )
    execute_trade(account, trade, headers)
    settled = settle_trade(account, trade, headers)
    return settled


def re_get_trade(account_id: str, trade_id: str,
                 headers: Optional[Dict[str, str]] = None,
                 ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    resp = api_client.get_trade(account_id, trade_id, headers)
    return get_success_data(resp)


# ===========================================================================
# Positions / lots / harvest helpers — PRD §3.4 / §3.7
# ===========================================================================
def list_positions(account_id: str,
                   headers: Optional[Dict[str, str]] = None,
                   params: Optional[Dict[str, Any]] = None,
                   ) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["advisor_headers"]
    resp = api_client.list_positions(account_id, headers, params)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return data.get("items", data.get("data", []))  # tolerate wrappers


def recompute_positions(account_id: str,
                        *,
                        intent: Optional[str] = None,
                        headers: Optional[Dict[str, str]] = None,
                        ) -> Any:
    headers = headers or TEST_USERS["advisor_headers"]
    payload: Dict[str, Any] = {}
    if intent is not None:
        payload["intent"] = intent
    resp = api_client.recompute_positions(account_id, payload, headers)
    return get_success_data(resp)


def recompute_drift(account_id: str,
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    resp = api_client.recompute_drift(account_id, headers)
    return get_success_data(resp)


def list_harvest_opportunities(account_id: str,
                               headers: Optional[Dict[str, str]] = None,
                               params: Optional[Dict[str, Any]] = None,
                               ) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["advisor_headers"]
    resp = api_client.list_harvest_opportunities(
        account_id, headers, params,
    )
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return data.get("items", data.get("data", []))


def list_trades(account_id: str,
                headers: Optional[Dict[str, str]] = None,
                params: Optional[Dict[str, Any]] = None,
                ) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["advisor_headers"]
    resp = api_client.list_trades(account_id, headers, params)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return data.get("items", data.get("data", []))


def list_rebalance_runs(account_id: str,
                        headers: Optional[Dict[str, str]] = None,
                        params: Optional[Dict[str, Any]] = None,
                        ) -> List[Dict[str, Any]]:
    headers = headers or TEST_USERS["advisor_headers"]
    resp = api_client.list_rebalance_runs(account_id, headers, params)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return data.get("items", data.get("data", []))


# ===========================================================================
# Tier 2: Activated-client + funded-account scenario — PRD §3.1 / §3.3
# ===========================================================================
def setup_active_client_with_account(
    *,
    birth_date: str = TEST_DEFAULTS["BIRTH_DATE"],
    time_horizon_years: int = TEST_DEFAULTS["TIME_HORIZON_YEARS"],
    fund_cents: int = TEST_DEFAULTS["ACCOUNT_FUNDING_CENTS"],
    risk_answers: Optional[Dict[str, int]] = None,
    seed_models: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build: ComplianceOfficer creates Client + Account; risk
    questionnaire submitted (defaults to MODERATE band); Client moved
    PENDING->ACTIVE; account funded.

    Returns (client, account).
    """
    if seed_models:
        seed_nine_model_portfolios()
    client = create_client(
        birth_date=birth_date,
        time_horizon_years=time_horizon_years,
    )
    account = create_account(client)
    answers = risk_answers or {
        "q1_loss_tolerance": 4,
        "q2_volatility_comfort": 4,
        "q3_growth_vs_stability": 3,
        "q4_liquidity_need": 3,
        "q5_experience": 3,
    }
    submit_questionnaire(client, **answers)
    activate_client(client)
    if fund_cents > 0:
        fund_account(account, fund_cents)
    # Re-fetch latest views.
    client = re_get_client(client["id"])
    account = re_get_account(account["id"])
    return client, account


# ===========================================================================
# Tier 3: BUY lot scenarios — for FIFO vs SPECIFIC_LOT testing
# ===========================================================================
def setup_two_lots_for_specific_vs_fifo(
    *,
    fund_cents: int = 5_000_000,
) -> Dict[str, Any]:
    """Build: Active Client + Account; one Security S1; two open Lots
    A and B for S1 (Lot A older at unit_cost=10000, Lot B newer at
    unit_cost=12000), 10 shares each. Re-price S1 to 11000. Used by
    fifo_vs_specific_lot_realized_gain.

    Returns dict with keys: client, account, security, lot_a, lot_b,
    buy_a, buy_b.
    """
    client, account = setup_active_client_with_account(fund_cents=fund_cents)
    # Use early dates so the lots are anchored before any test-driven
    # window.
    advance_clock_to(iso_instant_utc(2024, 1, 1, 12, 0, 0))
    security = create_security(
        last_price_cents=10_000,
        asset_class="US_EQUITY",
    )
    # Lot A: 10 shares at 10000 (older).
    buy_a = buy_and_settle(account, security, 10)
    advance_clock_to(iso_instant_utc(2024, 6, 1, 12, 0, 0))
    set_pricing(security, 12_000)
    # Lot B: 10 shares at 12000 (newer).
    buy_b = buy_and_settle(account, security, 10)
    # Reprice to 11000 (today) — what the SELL will execute at.
    advance_clock_to(iso_instant_utc(2024, 12, 1, 12, 0, 0))
    set_pricing(security, 11_000)
    return {
        "client": client,
        "account": account,
        "security": security,
        "buy_a": buy_a,
        "buy_b": buy_b,
    }


# ===========================================================================
# Tier 3: Drift-at-threshold scenario — PRD §3.8 boundary
# ===========================================================================
def setup_account_with_drift(
    *,
    target_drift_pct: float,
    fund_cents: int = 1_000_000,
) -> Dict[str, Any]:
    """Build: Account holding two securities US_EQUITY and US_BOND
    such that, against a 60/40 model, the max drift equals
    target_drift_pct (approximately).

    Heuristic: choose a 60/40 single-class model (US_EQUITY=60%,
    US_BOND=40%, others=0). Buy enough US_EQUITY and US_BOND so that
    (us_equity_mv / total_mv - 0.6) == target_drift_pct/100.

    Returns dict with client, account, security_eq, security_bond,
    model.
    """
    # Custom 60/40 allocation for predictable drift math.
    alloc = {
        "US_EQUITY": 0.60,
        "INTL_EQUITY": 0.00,
        "US_BOND": 0.40,
        "INTL_BOND": 0.00,
        "CASH": 0.00,
    }
    # The default TIME_HORIZON_YEARS is 20 which resolves to the LONG
    # horizon-band (PRD §3.2: LONG covers years sixteen through forty),
    # and the default questionnaire answers compute to MODERATE risk_band.
    # Override the (MODERATE, LONG) bucket — the one actually selected
    # by assign_models_for_client for a setup_active_client_with_account
    # call — with our predictable 60/40 alloc. We override every bucket
    # defensively in case other tests rely on this fixture with
    # different defaults.
    grid = {(rb, hb): alloc for rb in ("CONSERVATIVE", "MODERATE", "AGGRESSIVE")
            for hb in ("SHORT", "MID", "LONG")}
    seed_nine_model_portfolios(target_allocations=grid)

    client, account = setup_active_client_with_account(
        fund_cents=fund_cents, seed_models=False,
    )

    eq = create_security(asset_class="US_EQUITY", last_price_cents=100)
    bd = create_security(asset_class="US_BOND", last_price_cents=100)
    # Total target MV = 1_000_000 cents. Goal: us_eq weight =
    # 0.6 + target_drift_pct/100; bond weight = 0.4 - target_drift_pct/100.
    total_cents = fund_cents
    eq_weight = 0.60 + (target_drift_pct / 100.0)
    bd_weight = 1.0 - eq_weight
    eq_mv = int(round(eq_weight * total_cents))
    bd_mv = int(round(bd_weight * total_cents))
    # price = 100 cents → shares = mv / 100.
    eq_shares = eq_mv / 100
    bd_shares = bd_mv / 100
    if eq_shares > 0:
        buy_and_settle(account, eq, eq_shares)
    if bd_shares > 0:
        buy_and_settle(account, bd, bd_shares)
    # Drift recompute to refresh max_drift_pct.
    recompute_drift(account["id"])
    account = re_get_account(account["id"])
    return {
        "client": client,
        "account": account,
        "security_eq": eq,
        "security_bond": bd,
        "model_allocation": alloc,
    }


# ===========================================================================
# Tier 4: Position with unrealized loss at boundary — PRD §3.7
# ===========================================================================
def setup_account_with_position_at_loss(
    *,
    unrealized_loss_cents_target: int,
    fund_cents: int = 2_000_000,
) -> Dict[str, Any]:
    """Build: Active funded Account; one Security S; one settled BUY
    so that the resulting Position has unrealized_loss_cents ==
    unrealized_loss_cents_target after a price set.

    Strategy: BUY 10 shares S at unit_cost=10000 (cost basis = 100000
    cents). Set price such that market_value = cost_basis +
    unrealized_loss_cents_target. price = (100000 + target) / 10.

    Returns dict with client, account, security, buy_trade.
    """
    client, account = setup_active_client_with_account(fund_cents=fund_cents)
    security = create_security(
        last_price_cents=10_000,
        asset_class="US_EQUITY",
    )
    buy = buy_and_settle(account, security, 10)
    new_price = (100_000 + unrealized_loss_cents_target) // 10
    set_pricing(security, new_price)
    return {
        "client": client,
        "account": account,
        "security": security,
        "buy_trade": buy,
    }


# ===========================================================================
# Tier 4: Wash-sale scenario — PRD §3.6
# ===========================================================================
def setup_wash_sale_scenario(
    *,
    sell_date_iso: str,
    buy_offset_days: int,
    sell_shares: float = 10.0,
    buy_shares: float = 5.0,
    fund_cents: int = 5_000_000,
) -> Dict[str, Any]:
    """Build a wash-sale candidate scenario for the symmetric ±30-day
    window:

    - Active Account funded.
    - Securities S_a and S_b sharing one substantially_identical_group_id.
    - BUY+settle of S_a at price 10000 well before any sell date (creates the
      position to be sold at a loss).
    - At sell_date_iso, drop S_a price so the upcoming SELL realizes a
      loss; record the BUY of S_b (substantially identical) at
      buy_offset_days offset from sell_date.

    Returns the dict {client, account, group_id, security_a, security_b,
    initial_buy, replacement_buy}.

    The caller still needs to: optionally place its OWN SELL to settle
    on sell_date_iso (use sell_shares as the sell quantity).
    """
    from datetime import datetime, timedelta

    client, account = setup_active_client_with_account(fund_cents=fund_cents)
    group_id = random_group_id()
    sec_a = create_security(
        substantially_identical_group_id=group_id,
        last_price_cents=10_000,
        ticker=random_ticker("A"),
    )
    sec_b = create_security(
        substantially_identical_group_id=group_id,
        last_price_cents=9_000,
        ticker=random_ticker("B"),
    )
    # Position: buy 10 shares S_a a long time before the sell date.
    sell_dt = datetime.fromisoformat(
        sell_date_iso.replace("Z", "+00:00"),
    )
    pre_buy_dt = sell_dt - timedelta(days=120)
    advance_clock_to(iso_instant_utc(
        pre_buy_dt.year, pre_buy_dt.month, pre_buy_dt.day,
    ))
    initial_buy = buy_and_settle(account, sec_a, sell_shares)
    # BUY of substantially-identical S_b at sell_date + buy_offset_days.
    buy_dt = sell_dt + timedelta(days=buy_offset_days)
    advance_clock_to(iso_instant_utc(buy_dt.year, buy_dt.month, buy_dt.day))
    set_pricing(sec_b, 9_000)
    replacement_buy = buy_and_settle(account, sec_b, buy_shares)
    return {
        "client": client,
        "account": account,
        "group_id": group_id,
        "security_a": sec_a,
        "security_b": sec_b,
        "initial_buy": initial_buy,
        "replacement_buy": replacement_buy,
    }


# ===========================================================================
# Tier 4: Harvest opportunity with replacement — PRD §3.7
# ===========================================================================
def setup_harvest_detected_with_replacement(
    *,
    unrealized_loss_cents_target: int = -60_000,
    fund_cents: int = 2_000_000,
) -> Dict[str, Any]:
    """Build: Active funded Account; held Security S_held; replacement
    Security S_repl in a different group; CorrelationLink between
    them; the Position on S_held has unrealized_loss_cents <=
    -MIN_HARVEST_THRESHOLD_CENTS. Trigger
    POST /accounts/{a}/positions/recompute?intent=detect.

    Returns dict with client, account, security_held, security_repl,
    opportunity (DETECTED), correlation_link.
    """
    client, account = setup_active_client_with_account(fund_cents=fund_cents)
    held = create_security(
        ticker=random_ticker("H"),
        substantially_identical_group_id=random_group_id(),
        asset_class="US_EQUITY",
        last_price_cents=10_000,
    )
    repl = create_security(
        ticker=random_ticker("R"),
        substantially_identical_group_id=random_group_id(),
        asset_class="US_EQUITY",
        last_price_cents=10_000,
    )
    correlation_link = create_correlation_link(held, repl, 0.95)
    # Buy 10 shares of S_held at 10000 = 100000 cents cost.
    buy_and_settle(account, held, 10)
    # Drop price to hit target unrealized loss.
    new_price = (100_000 + unrealized_loss_cents_target) // 10
    set_pricing(held, new_price)
    # Trigger detection.
    recompute_positions(account["id"], intent="detect")
    opps = list_harvest_opportunities(account["id"])
    opp = next((o for o in opps if o.get("status") == "DETECTED"), None)
    return {
        "client": client,
        "account": account,
        "security_held": held,
        "security_repl": repl,
        "correlation_link": correlation_link,
        "opportunity": opp,
    }


def setup_harvest_blocked_no_replacement(
    *,
    unrealized_loss_cents_target: int = -60_000,
    fund_cents: int = 2_000_000,
) -> Dict[str, Any]:
    """Same as setup_harvest_detected_with_replacement but WITHOUT a
    CorrelationLink — opportunity goes BLOCKED."""
    client, account = setup_active_client_with_account(fund_cents=fund_cents)
    held = create_security(
        ticker=random_ticker("H"),
        substantially_identical_group_id=random_group_id(),
        asset_class="US_EQUITY",
        last_price_cents=10_000,
    )
    buy_and_settle(account, held, 10)
    new_price = (100_000 + unrealized_loss_cents_target) // 10
    set_pricing(held, new_price)
    recompute_positions(account["id"], intent="detect")
    opps = list_harvest_opportunities(account["id"])
    opp = next(
        (o for o in opps if o.get("status") == "BLOCKED"), None,
    )
    return {
        "client": client,
        "account": account,
        "security_held": held,
        "opportunity": opp,
    }


# ===========================================================================
# Tier 4: Funded account with BUY trade ready to execute — PRD §2.7 priority
# ===========================================================================
def setup_pending_buy_trade(
    *,
    requested_shares: float = 5,
    security_kwargs: Optional[Dict[str, Any]] = None,
    fund_cents: int = 1_000_000,
) -> Dict[str, Any]:
    """Active funded Account + Security + PENDING BUY trade. Returns
    {client, account, security, trade}.
    """
    client, account = setup_active_client_with_account(fund_cents=fund_cents)
    sk = security_kwargs or {}
    security = create_security(
        last_price_cents=10_000,
        **sk,
    )
    trade = create_trade(
        account, security,
        side="BUY", requested_shares=requested_shares,
    )
    return {
        "client": client,
        "account": account,
        "security": security,
        "trade": trade,
    }


def setup_frozen_account_with_pending_buy(
    *,
    requested_shares: float = 5,
    cash_balance_cents: int = 100,  # insufficient for buy
    fund_cents: int = 100,  # tiny so insufficient cash also applies
) -> Dict[str, Any]:
    """Build a Frozen Account + PENDING BUY trade whose execution
    would also fail the insufficient-cash check. Used to verify
    validation-priority order (state-vs-fiscal): PRD §2.7 says
    ERR_ACCOUNT_FROZEN wins.
    """
    client, account = setup_active_client_with_account(
        fund_cents=fund_cents,
    )
    security = create_security(last_price_cents=10_000)
    trade = create_trade(
        account, security,
        side="BUY", requested_shares=requested_shares,
    )
    freeze_account(account)
    return {
        "client": client,
        "account": account,
        "security": security,
        "trade": trade,
    }


# ===========================================================================
# Tier 5: Form 1099-B scenario — PRD §3.11
# ===========================================================================
def create_form_1099b(client: Dict[str, Any], tax_year: int,
                      headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["tax_admin_headers"]
    payload = create_form_1099b_payload(tax_year=tax_year)
    resp = api_client.create_form_1099b(
        client["id"], payload, headers,
    )
    return get_success_data(resp)


def re_get_form_1099b(client_id: str, form_id: str,
                      headers: Optional[Dict[str, str]] = None,
                      ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["tax_admin_headers"]
    resp = api_client.get_form_1099b(client_id, form_id, headers)
    return get_success_data(resp)


def issue_form_1099b(client: Dict[str, Any], form: Dict[str, Any],
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["tax_admin_headers"]
    resp = api_client.issue_form_1099b(
        client["id"], form["id"], headers,
    )
    return get_success_data(resp)


def void_form_1099b(client: Dict[str, Any], form: Dict[str, Any],
                    headers: Optional[Dict[str, str]] = None,
                    ) -> Dict[str, Any]:
    headers = headers or TEST_USERS["tax_admin_headers"]
    resp = api_client.void_form_1099b(
        client["id"], form["id"], headers,
    )
    return get_success_data(resp)


# ===========================================================================
# Dividend helpers — PRD §3.10
# ===========================================================================
def record_dividend(
    account: Dict[str, Any],
    security: Dict[str, Any],
    amount_cents: int,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    payload = record_dividend_payload(
        security_id=security["id"], amount_cents=amount_cents,
    )
    resp = api_client.record_dividend(account["id"], payload, headers)
    return get_success_data(resp)


# ===========================================================================
# Rebalance helpers — PRD §3.8
# ===========================================================================
def start_rebalance(
    account: Dict[str, Any],
    *,
    quarter_key: str,
    force: Optional[bool] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    headers = headers or TEST_USERS["advisor_headers"]
    payload: Dict[str, Any] = {"quarter_key": quarter_key}
    if force is not None:
        payload["force"] = force
    resp = api_client.start_rebalance(
        account["id"], payload, headers,
    )
    return get_success_data(resp)


__all__ = [
    # Clock
    "advance_clock_to",
    "advance_clock_tick",
    # Client
    "create_client",
    "submit_questionnaire",
    "activate_client",
    "suspend_client",
    "reinstate_client",
    "re_get_client",
    # Model portfolio
    "create_model_portfolio",
    "seed_nine_model_portfolios",
    # Security / pricing / correlation
    "create_security",
    "set_pricing",
    "create_correlation_link",
    # Account
    "create_account",
    "fund_account",
    "freeze_account",
    "unfreeze_account",
    "re_get_account",
    # Trades
    "create_trade",
    "execute_trade",
    "settle_trade",
    "execute_and_settle",
    "buy_and_settle",
    "sell_and_settle",
    "re_get_trade",
    # Listings & recomputes
    "list_positions",
    "recompute_positions",
    "recompute_drift",
    "list_harvest_opportunities",
    "list_trades",
    "list_rebalance_runs",
    # Composite setups
    "setup_active_client_with_account",
    "setup_two_lots_for_specific_vs_fifo",
    "setup_account_with_drift",
    "setup_account_with_position_at_loss",
    "setup_wash_sale_scenario",
    "setup_harvest_detected_with_replacement",
    "setup_harvest_blocked_no_replacement",
    "setup_pending_buy_trade",
    "setup_frozen_account_with_pending_buy",
    # Form 1099-B
    "create_form_1099b",
    "re_get_form_1099b",
    "issue_form_1099b",
    "void_form_1099b",
    # Dividend & rebalance
    "record_dividend",
    "start_rebalance",
]
