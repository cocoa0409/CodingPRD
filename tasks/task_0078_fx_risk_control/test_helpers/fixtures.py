"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup
failures produce clear "Setup failed" errors instead of confusing assertion
failures.

All fixtures honor PRD §2.1 identity rules:
- Trader headers are minted per-Trader via make_trader_headers(trader["id"])
  — never the shared TEST_USERS["trader_headers"] fallback, which would fail
  every ownership check.
- Opaque-role headers (RiskOfficer, ComplianceOfficer, SettlementOperator,
  MarketDataSystem) use the shared TEST_USERS constants.

Segregation-of-duties (PRD §3.3, §3.5):
- RiskOfficer approving a request must have an X-User-ID distinct from the
  trader's id (the request's requester_trader_id). Since RiskOfficer is
  opaque, any of the canned risk-officer constants works.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    LARGE_TRADE_THRESHOLD_USD,
    TEST_DEFAULTS,
)
from .factories import (
    advance_clock_payload,
    create_counterparty_payload,
    create_currency_pair_payload,
    create_limit_adjustment_payload,
    create_limit_payload,
    create_stop_loss_payload,
    create_trade_payload,
    create_trader_payload,
    generate_settlements_payload,
    post_market_quote_payload,
)
from .test_users import (
    TEST_USERS,
    make_trader_headers,
)


# ===========================================================================
# Tier 0: Clock setup
# ===========================================================================
def set_clock(to_iso: str) -> None:
    """POST /fx-risk/_clock/advance — pins the server clock to a known
    instant before tests inspect time-gated state. PRD §2.12."""
    res = api_client.advance_clock(
        advance_clock_payload(to_iso),
        TEST_USERS["risk_officer_headers"],
    )
    get_success_data(res)


def run_sweep() -> Dict[str, Any]:
    """POST /fx-risk/_sweep/run — walks the 6-step EOD cascade. PRD §3.10."""
    res = api_client.run_sweep(TEST_USERS["risk_officer_headers"])
    return get_success_data(res)


# ===========================================================================
# Tier 1: Individual entity creation
# ===========================================================================
def create_trader(
    *,
    name: Optional[str] = None,
    desk_code: str = TEST_DEFAULTS["DESK_CODE"],
) -> Dict[str, Any]:
    """Create a Trader. Returns the created row (status=ACTIVE on creation)."""
    payload = create_trader_payload(
        name=name or f"trader-{uuid.uuid4().hex[:8]}",
        desk_code=desk_code,
    )
    res = api_client.create_trader(payload, TEST_USERS["risk_officer_headers"])
    return get_success_data(res)


def create_currency_pair(
    *,
    code: str = TEST_DEFAULTS["PAIR_CODE"],
    base_ccy: Optional[str] = None,
    quote_ccy: Optional[str] = None,
    mid_rate: float = TEST_DEFAULTS["PAIR_MID_RATE"],
    daily_volatility: float = TEST_DEFAULTS["PAIR_VOL"],
) -> Dict[str, Any]:
    """Create a CurrencyPair. base_ccy/quote_ccy default to code[0:3]/code[3:6]."""
    payload = create_currency_pair_payload(
        code=code,
        base_ccy=base_ccy or code[0:3],
        quote_ccy=quote_ccy or code[3:6],
        mid_rate=mid_rate,
        daily_volatility=daily_volatility,
    )
    res = api_client.create_currency_pair(
        payload, TEST_USERS["risk_officer_headers"],
    )
    return get_success_data(res)


def post_quote(code: str, mid_rate: float) -> Dict[str, Any]:
    """POST /fx-risk/market-data/quote. PRD §3.1 cascade is server-driven."""
    res = api_client.post_market_quote(
        post_market_quote_payload(code, mid_rate),
        TEST_USERS["market_data_headers"],
    )
    return get_success_data(res)


def create_counterparty(
    *,
    name: Optional[str] = None,
    external_rating: str = "AAA",
    internal_score: int = 90,
) -> Dict[str, Any]:
    """Create a Counterparty. Defaults: AAA + 90 → INVESTMENT, not on watchlist."""
    payload = create_counterparty_payload(
        name=name or f"cp-{uuid.uuid4().hex[:8]}",
        external_rating=external_rating,
        internal_score=internal_score,
    )
    res = api_client.create_counterparty(
        payload, TEST_USERS["compliance_officer_headers"],
    )
    return get_success_data(res)


def create_limit(
    trader_id: str,
    *,
    bucket: str,
    notional_cap_usd: float,
    pair_code: Optional[str] = None,
    stop_loss_cap_usd: float = TEST_DEFAULTS["STOP_LOSS_CAP_USD"],
) -> Dict[str, Any]:
    """Create a Limit row for a trader."""
    payload = create_limit_payload(
        bucket=bucket,
        notional_cap_usd=notional_cap_usd,
        pair_code=pair_code,
        stop_loss_cap_usd=stop_loss_cap_usd,
    )
    res = api_client.create_limit(
        trader_id, payload, TEST_USERS["risk_officer_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2: Common composite scenarios
# ===========================================================================
def _unique_pair_code() -> str:
    """Mint a unique six-uppercase-letter pair code per call so that
    fixtures invoked twice in the same test (or twice within a process)
    never collide on the §3.1 'a row with the same code already exists'
    rejection. Base letters chosen from a stable 26-letter alphabet keyed
    on uuid4 so collisions inside a single test run are vanishingly rare.
    """
    h = uuid.uuid4().hex
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "".join(letters[int(h[i:i + 2], 16) % 26] for i in range(0, 12, 2))


def setup_trader_with_limits(
    *,
    desk_code: str = TEST_DEFAULTS["DESK_CODE"],
    pair_code: Optional[str] = None,
    intraday_cap: float = TEST_DEFAULTS["INTRADAY_CAP_USD"],
    overnight_cap: float = TEST_DEFAULTS["OVERNIGHT_CAP_USD"],
    create_pair: bool = True,
    pair_mid_rate: float = TEST_DEFAULTS["PAIR_MID_RATE"],
    pair_volatility: float = TEST_DEFAULTS["PAIR_VOL"],
    counterparty_external_rating: str = "AAA",
    counterparty_internal_score: int = 90,
    clock_iso: str = TEST_DEFAULTS["CLOCK_INTRADAY_ISO"],
) -> Dict[str, Any]:
    """The most common scenario: a Trader with INTRADAY+OVERNIGHT Limits on a
    CurrencyPair plus an INVESTMENT-grade Counterparty. Clock is pinned to
    an intraday instant (PRD §3.2 < 17:00 UTC) so trades default to INTRADAY.

    Returns a dict with keys: trader, pair, counterparty, intraday_limit,
    overnight_limit, trader_headers.
    """
    set_clock(clock_iso)
    # Mint a fresh, unique pair code per call by default so that
    # multi-call tests (e.g., two `setup_trader_with_limits` for
    # different traders in the same test) do not collide on the
    # §3.1 'a row with the same code already exists' rejection.
    effective_code = pair_code if pair_code is not None else _unique_pair_code()
    if create_pair:
        pair = create_currency_pair(
            code=effective_code,
            mid_rate=pair_mid_rate,
            daily_volatility=pair_volatility,
        )
    else:
        pair = None
    trader = create_trader(desk_code=desk_code)
    counterparty = create_counterparty(
        external_rating=counterparty_external_rating,
        internal_score=counterparty_internal_score,
    )
    intraday_limit = create_limit(
        trader["id"],
        bucket="INTRADAY",
        notional_cap_usd=intraday_cap,
        pair_code=effective_code,
    )
    overnight_limit = create_limit(
        trader["id"],
        bucket="OVERNIGHT",
        notional_cap_usd=overnight_cap,
        pair_code=effective_code,
    )
    return {
        "trader": trader,
        "pair": pair,
        "counterparty": counterparty,
        "intraday_limit": intraday_limit,
        "overnight_limit": overnight_limit,
        "trader_headers": make_trader_headers(trader["id"]),
    }


def book_trade(
    *,
    trader_id: str,
    pair_code: str,
    side: str,
    notional_base: float,
    entry_rate: float,
    counterparty_id: str,
) -> Dict[str, Any]:
    """Book a Trade as the named trader (PRD §3.4 — trader_id must equal
    the caller's X-User-ID for the request to be accepted)."""
    res = api_client.create_trade(
        create_trade_payload(
            pair_code=pair_code,
            side=side,
            notional_base=notional_base,
            entry_rate=entry_rate,
            counterparty_id=counterparty_id,
        ),
        make_trader_headers(trader_id),
    )
    return get_success_data(res)


# ===========================================================================
# Tier 3: Limit adjustment workflow
# ===========================================================================
def create_pending_adjustment(
    *,
    trader_id: str,
    limit_id: str,
    requested_delta_usd: float = 1_000_000.00,
    justification: str = "Volume spike",
    expires_at: str = TEST_DEFAULTS["EXPIRES_FAR_FUTURE"],
) -> Dict[str, Any]:
    """POST /fx-risk/limit-adjustments as the trader. Returns PENDING request."""
    res = api_client.create_limit_adjustment(
        create_limit_adjustment_payload(
            limit_id=limit_id,
            requested_delta_usd=requested_delta_usd,
            justification=justification,
            expires_at=expires_at,
        ),
        make_trader_headers(trader_id),
    )
    return get_success_data(res)


def approve_adjustment(adj_id: str) -> Dict[str, Any]:
    """POST /fx-risk/limit-adjustments/{id}/approve as a RiskOfficer.

    PRD §3.3 segregation: the officer's X-User-ID must differ from
    requester_trader_id. Since RiskOfficer is opaque (PRD §2.1), the canned
    risk_officer constant ('risk-officer-001') is always distinct from any
    real Trader.id (which is a server-minted UUID).
    """
    res = api_client.approve_limit_adjustment(
        adj_id, TEST_USERS["risk_officer_headers"],
    )
    return get_success_data(res)


def reject_adjustment(adj_id: str) -> Dict[str, Any]:
    res = api_client.reject_limit_adjustment(
        adj_id, TEST_USERS["risk_officer_headers"],
    )
    return get_success_data(res)


def request_revision_adjustment(adj_id: str) -> Dict[str, Any]:
    res = api_client.request_revision_limit_adjustment(
        adj_id, TEST_USERS["risk_officer_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 4: Stop-loss
# ===========================================================================
def create_stop_loss(
    *,
    trader_id: str,
    pair_code: str,
    rule_mode: str,
    threshold_value: float,
    action: str,
) -> Dict[str, Any]:
    """POST /fx-risk/stop-loss (RiskOfficer). Returns the ARMED rule."""
    res = api_client.create_stop_loss(
        create_stop_loss_payload(
            trader_id=trader_id,
            pair_code=pair_code,
            rule_mode=rule_mode,
            threshold_value=threshold_value,
            action=action,
        ),
        TEST_USERS["risk_officer_headers"],
    )
    return get_success_data(res)


def setup_long_position_with_price_stop(
    *,
    intraday_cap: float = TEST_DEFAULTS["INTRADAY_CAP_USD"],
    notional_base: float = 1_000_000.00,
    pair_mid_rate: float = 1.100000,
    threshold_value: float = 1.0950,
    action: str = "ALERT",
    clock_iso: str = TEST_DEFAULTS["CLOCK_INTRADAY_ISO"],
) -> Dict[str, Any]:
    """Build a long EURUSD position and arm a PRICE stop-loss.

    Returns dict with: ctx (from setup_trader_with_limits), trade,
    stop_loss. The stop is ARMED with the given threshold_value.
    """
    ctx = setup_trader_with_limits(
        pair_mid_rate=pair_mid_rate,
        intraday_cap=intraday_cap,
        clock_iso=clock_iso,
    )
    trade = book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        side="BUY",
        notional_base=notional_base,
        entry_rate=pair_mid_rate,
        counterparty_id=ctx["counterparty"]["id"],
    )
    sl = create_stop_loss(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        rule_mode="PRICE",
        threshold_value=threshold_value,
        action=action,
    )
    return {"ctx": ctx, "trade": trade, "stop_loss": sl}


def setup_triggered_forced_flatten(
    *,
    pair_mid_rate: float = 1.100000,
    threshold_value: float = 1.0950,
    notional_base: float = 1_000_000.00,
) -> Dict[str, Any]:
    """Build a long position with a FORCED_FLATTEN PRICE stop, then push a
    quote at the threshold to trigger it. Returns ctx + trade + stop_loss
    (now in TRIGGERED state).

    PRD §3.5: 'On any ARMED rule's first crossing, the system transitions
    the rule from ARMED to TRIGGERED.'
    """
    state = setup_long_position_with_price_stop(
        pair_mid_rate=pair_mid_rate,
        threshold_value=threshold_value,
        notional_base=notional_base,
        action="FORCED_FLATTEN",
    )
    # Crossing quote pulls the stop into TRIGGERED.
    post_quote(state["ctx"]["pair"]["code"], threshold_value)
    # Refresh the stop-loss view via list-positions or re-evaluate.
    res = api_client.evaluate_stop_loss(
        state["stop_loss"]["id"],
        TEST_USERS["risk_officer_headers"],
    )
    triggered = get_success_data(res)
    state["stop_loss"] = triggered
    return state


# ===========================================================================
# Tier 5: Settlement / netting
# ===========================================================================
def setup_settlement_generated(
    *,
    notional_base: float = 1_000_000.00,
    entry_rate: float = 1.100000,
    side: str = "BUY",
    pair_code: str = "EURUSD",
    pair_mid_rate: float = 1.100000,
    counterparty_external_rating: str = "AAA",
    counterparty_internal_score: int = 90,
    value_date: str = "2026-05-14",
    client_request_id: Optional[str] = None,
    intraday_cap: float = 50_000_000.00,
) -> Dict[str, Any]:
    """Book a single trade, then generate a SettlementInstruction set.

    Returns dict: ctx, trade, instructions (list of SettlementInstruction
    rows, one per currency).

    Note: PRD §3.4 forbids booking a trade against a WATCH-band
    counterparty (ERR_TRADER_SUSPENDED). If the requested counterparty
    inputs would yield WATCH band on creation, we provision the
    counterparty with a safe starting score, book the trade, then PATCH
    the counterparty down to the requested score so the test scenario
    can still exercise WATCH-band-driven cascades afterwards.
    """
    from .constants import band_from_external, band_from_internal, worse_band

    starting_external = counterparty_external_rating
    starting_internal = counterparty_internal_score
    initial_band = worse_band(
        band_from_external(counterparty_external_rating),
        band_from_internal(counterparty_internal_score),
    )
    needs_post_patch = initial_band == "WATCH"
    if needs_post_patch:
        # Provision a STANDARD-band counterparty (A rating, score 70) for
        # the booking step; we will patch back to the requested values
        # before returning so the caller still observes the intended
        # state.
        starting_external = "A"
        starting_internal = 70
    ctx = setup_trader_with_limits(
        pair_code=pair_code,
        pair_mid_rate=pair_mid_rate,
        intraday_cap=intraday_cap,
        counterparty_external_rating=starting_external,
        counterparty_internal_score=starting_internal,
    )
    trade = book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=pair_code,
        side=side,
        notional_base=notional_base,
        entry_rate=entry_rate,
        counterparty_id=ctx["counterparty"]["id"],
    )
    if needs_post_patch:
        cp_after = get_success_data(
            api_client.patch_counterparty(
                ctx["counterparty"]["id"],
                {
                    "version": ctx["counterparty"]["version"],
                    "external_rating": counterparty_external_rating,
                    "internal_score": counterparty_internal_score,
                },
                TEST_USERS["compliance_officer_headers"],
            )
        )
        ctx["counterparty"] = cp_after
    crid = client_request_id or f"cri-{uuid.uuid4().hex}"
    res = api_client.generate_settlements(
        generate_settlements_payload(
            counterparty_id=ctx["counterparty"]["id"],
            value_date=value_date,
            client_request_id=crid,
        ),
        TEST_USERS["settlement_operator_headers"],
    )
    instructions = get_success_data(res)
    if isinstance(instructions, dict):
        instructions = [instructions]
    return {
        "ctx": ctx,
        "trade": trade,
        "instructions": instructions,
        "client_request_id": crid,
        "value_date": value_date,
    }


def setup_sent_settlement_for_failure_cascade(
    *,
    counterparty_external_rating: str = "BBB",
    counterparty_internal_score: int = 44,
    notional_base: float = 9_000_000.00,
    entry_rate: float = 1.000000,
    pair_mid_rate: float = 1.000000,
    intraday_cap: float = 50_000_000.00,
) -> Dict[str, Any]:
    """Build the depth-4-cascade scenario:
      Counterparty starts in SPECULATIVE band (BBB external + 44 internal),
      Trader books a 9M USD trade facing it,
      SettlementInstruction is generated and SENT,
    so a subsequent /mark-failed triggers the full cascade
    (PRD §3.7 step 4: internal_score -= 5 → score=39 → band=WATCH →
     credit_limit=1M → trader.status=SUSPENDED because 9M > 1M).

    Returns dict: ctx, trade, instructions, sent_instruction_id, value_date.
    """
    s = setup_settlement_generated(
        notional_base=notional_base,
        entry_rate=entry_rate,
        side="BUY",
        pair_mid_rate=pair_mid_rate,
        counterparty_external_rating=counterparty_external_rating,
        counterparty_internal_score=counterparty_internal_score,
        intraday_cap=intraday_cap,
    )
    # Pick the USD-side instruction (the one we PAY out is the more
    # interesting one to flip into SENT, but for the cascade either works).
    si = s["instructions"][0]
    sent = get_success_data(
        api_client.send_settlement(si["id"], TEST_USERS["settlement_operator_headers"])
    )
    s["sent_instruction"] = sent
    return s


# ===========================================================================
# Tier 6: Threshold-targeting fixtures for boundary tests
# ===========================================================================
def setup_warning_boundary_intraday(
    *,
    intraday_cap: float = 10_000_000.00,
    overnight_cap: float = 10_000_000.00,
    pair_mid_rate: float = 1.000000,
) -> Dict[str, Any]:
    """Trader with USD-equivalent caps that make warning boundary
    arithmetic trivial: 1M USD position → 10% utilization.

    Returns the same dict as setup_trader_with_limits. Tests then book
    trades of specific notional_base to land at exact utilization_pct.
    """
    return setup_trader_with_limits(
        intraday_cap=intraday_cap,
        overnight_cap=overnight_cap,
        pair_mid_rate=pair_mid_rate,
    )


def book_to_reach_utilization(
    ctx: Dict[str, Any],
    target_notional_usd: float,
    *,
    side: str = "BUY",
    entry_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """Book a single Trade that pushes Position.net_open_usd to roughly
    target_notional_usd. For a USD-quoted pair with mid_rate=1.0, this is
    just notional_base == target_notional_usd."""
    pair_code = ctx["pair"]["code"]
    rate = entry_rate if entry_rate is not None else ctx["pair"]["mid_rate"]
    # Convert target_notional_usd → notional_base when quote is USD.
    notional_base = target_notional_usd / rate
    return book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=pair_code,
        side=side,
        notional_base=round(notional_base, 2),
        entry_rate=rate,
        counterparty_id=ctx["counterparty"]["id"],
    )


# ===========================================================================
# Tier 7: BREACH-then-approve fixture for depth-3 cascade
# ===========================================================================
def setup_breached_position_with_pending_adjustment(
    *,
    intraday_cap: float = 5_000_000.00,
    notional_base: float = 5_500_000.00,
    requested_delta_usd: float = 2_000_000.00,
) -> Dict[str, Any]:
    """Set up a trader whose Position is at BREACH (utilization_usd > cap)
    against a tight cap, plus a PENDING LimitAdjustmentRequest that — when
    approved — raises the effective cap above utilization_usd.

    Implementation note: PRD §3.4 rejects trade booking that would itself
    breach the cap, so we cannot reach BREACH by booking a too-large trade.
    Instead we book the trade against a generous cap and then PATCH the
    cap down to `intraday_cap` (PRD §3.2: 'Direct edits to a base cap are
    confined to a RiskOfficer patching the Limit row to change
    notional_cap_usd ...'). After the patch, the cached fixture row may
    be stale, so we refresh `intraday_limit` from the patch response.

    Returns dict: ctx (with up-to-date intraday_limit), trade, request.
    """
    # Use an interim cap large enough to admit the trade, and keep
    # the OVERNIGHT cap permanently high so the approval cascade on
    # the INTRADAY limit can drive Position.warning_status without
    # being clipped by an OVERNIGHT-only breach (the approval workflow
    # in PRD §3.3 only adds temporary_override to the targeted Limit).
    interim_cap = max(intraday_cap, notional_base) * 2.0
    ctx = setup_trader_with_limits(
        intraday_cap=interim_cap,
        overnight_cap=interim_cap * 10,
    )
    trade = book_trade(
        trader_id=ctx["trader"]["id"],
        pair_code=ctx["pair"]["code"],
        side="BUY",
        notional_base=notional_base,
        entry_rate=1.0,
        counterparty_id=ctx["counterparty"]["id"],
    )
    # Now patch the INTRADAY cap down to the target so utilization > 100%
    # → BREACH. The patch endpoint does NOT itself reject on a post-write
    # breach; it only rebaselines the cap (PRD §3.2: 'It simply
    # re-baselines the cap and is distinct from a temporary additive
    # override.').
    patch_res = api_client.patch_limit(
        ctx["intraday_limit"]["id"],
        {"notional_cap_usd": intraday_cap,
         "version": ctx["intraday_limit"]["version"]},
        TEST_USERS["risk_officer_headers"],
    )
    updated_intraday = get_success_data(patch_res)
    ctx["intraday_limit"] = updated_intraday
    request = create_pending_adjustment(
        trader_id=ctx["trader"]["id"],
        limit_id=ctx["intraday_limit"]["id"],
        requested_delta_usd=requested_delta_usd,
    )
    return {"ctx": ctx, "trade": trade, "request": request}


__all__ = [
    "set_clock",
    "run_sweep",
    "create_trader",
    "create_currency_pair",
    "post_quote",
    "create_counterparty",
    "create_limit",
    "setup_trader_with_limits",
    "book_trade",
    "create_pending_adjustment",
    "approve_adjustment",
    "reject_adjustment",
    "request_revision_adjustment",
    "create_stop_loss",
    "setup_long_position_with_price_stop",
    "setup_triggered_forced_flatten",
    "setup_settlement_generated",
    "setup_sent_settlement_for_failure_cascade",
    "setup_warning_boundary_intraday",
    "book_to_reach_utilization",
    "setup_breached_position_with_pending_adjustment",
]
