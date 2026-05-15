"""Position, limit-utilisation, and exposure recomputation.

Implements:
- §1.3 net_open_position
- §1.3 limit_utilization (intraday + overnight bucketing)
- §1.3 gross_exposure / net exposure
- §1.3 value_at_risk
- warning_status derivation
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Optional

from app.clock import parse_iso
from app.numeric import round_half_up, to_decimal, ZERO
from app.services.fx import base_in_usd_rate, usd_rate_for_ccy
from app.store import Store, new_id, now_iso


Z_99 = Decimal("2.326")
WARNING_PCT = Decimal("80")
BREACH_PCT = Decimal("100")
EOD_CUTOFF_HOUR = 17  # UTC


def _bucket_for_trade(trade: dict, current_trading_day: str) -> str:
    """Return INTRADAY or OVERNIGHT for a single trade given today's date.

    Same-day trades booked before 17:00 UTC are INTRADAY; same-day trades
    at or after 17:00 UTC, and any trade from a prior trading_day,
    contribute to OVERNIGHT.  17:00:00.000 itself counts as OVERNIGHT.
    """
    if trade["trading_day"] != current_trading_day:
        return "OVERNIGHT"
    executed = parse_iso(trade["executed_at"])
    if executed.hour >= EOD_CUTOFF_HOUR:
        return "OVERNIGHT"
    return "INTRADAY"


def _trade_included_for_bucket(trade: dict, bucket: str,
                               current_trading_day: str) -> bool:
    """PRD §3.2: overnight is a WIDER inclusion set than intraday — the
    overnight cap aggregates BOTH intraday and overnight-positioned trades
    on the same trading day, so 'the same trader at the same instant
    produces two distinct utilization_pct numbers — one per bucket — and
    both must hold.'
    """
    if bucket == "INTRADAY":
        return _bucket_for_trade(trade, current_trading_day) == "INTRADAY"
    # OVERNIGHT — include every BOOKED trade on this trading day, plus
    # carry-overs from prior trading days.
    return True


def _signed_base_for_trade(trade: dict) -> Decimal:
    notional = to_decimal(trade["notional_base"])
    return notional if trade["side"] == "BUY" else -notional


def _trades_for_position(store: Store, trader_id: str, pair_code: str) -> list[dict]:
    return [
        t for t in store.trades.values()
        if t["trader_id"] == trader_id
        and t["pair_code"] == pair_code
        and t["status"] == "BOOKED"
    ]


def _sorted_trades(trades: Iterable[dict]) -> list[dict]:
    return sorted(trades, key=lambda t: (t["executed_at"], t["id"]))


def _get_or_create_position(store: Store, trader_id: str, pair_code: str) -> dict:
    key = (trader_id, pair_code)
    pid = store.position_index.get(key)
    if pid is not None:
        return store.positions[pid]
    ts = now_iso()
    row = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "trader_id": trader_id,
        "pair_code": pair_code,
        "net_base": ZERO,
        "net_open_usd": ZERO,
        "mtm_pnl_usd": ZERO,
        "warning_status": "NORMAL",
    }
    store.positions[row["id"]] = row
    store.position_index[key] = row["id"]
    return row


def recompute_position(store: Store, trader_id: str, pair_code: str,
                       current_trading_day: str) -> dict:
    """Recompute (net_base, net_open_usd, mtm_pnl_usd) for a (trader, pair).

    Uses BOOKED trades whose trading_day == current_trading_day, sorted
    by executed_at ASC then id ASC.
    """
    pair_id = store.pair_index_by_code.get(pair_code)
    if pair_id is None:
        # Pair vanished — keep an empty position.
        position = _get_or_create_position(store, trader_id, pair_code)
        position["net_base"] = ZERO
        position["net_open_usd"] = ZERO
        position["mtm_pnl_usd"] = ZERO
        position["updated_at"] = now_iso()
        return position

    pair = store.currency_pairs[pair_id]
    included = [
        t for t in _trades_for_position(store, trader_id, pair_code)
        if t["trading_day"] == current_trading_day
    ]
    included = _sorted_trades(included)

    signed_base = ZERO
    pnl_usd = ZERO
    rate_usd_per_base = base_in_usd_rate(store, pair)
    current_mid = to_decimal(pair["mid_rate"])
    rate_usd_per_quote = usd_rate_for_ccy(store, pair["quote_ccy"]) or current_mid

    for trade in included:
        delta = _signed_base_for_trade(trade)
        signed_base = signed_base + delta
        # PnL = (current_mid - entry_rate) for BUY, (entry_rate - current_mid) for SELL,
        # multiplied by notional_base and converted into USD via the quote-ccy USD rate.
        entry = to_decimal(trade["entry_rate"])
        notional = to_decimal(trade["notional_base"])
        if trade["side"] == "BUY":
            pnl_quote = (current_mid - entry) * notional
        else:
            pnl_quote = (entry - current_mid) * notional
        if pair["quote_ccy"] == "USD":
            pnl_usd = pnl_usd + pnl_quote
        else:
            pnl_usd = pnl_usd + (pnl_quote * rate_usd_per_quote)

    net_open_usd = round_half_up(signed_base * rate_usd_per_base, 2)

    position = _get_or_create_position(store, trader_id, pair_code)
    position["net_base"] = round_half_up(signed_base, 2)
    position["net_open_usd"] = net_open_usd
    position["mtm_pnl_usd"] = round_half_up(pnl_usd, 2)
    position["updated_at"] = now_iso()
    # Position is recomputed as a side effect of trade booking / quote
    # cascades; version is not bumped on derived-field recompute (see
    # recompute_limit_utilization for the same convention).
    return position


def recompute_all_positions_for_pair(store: Store, pair_code: str,
                                     current_trading_day: str) -> list[dict]:
    """Walk every (trader, pair) tuple for this pair_code and recompute."""
    affected: list[dict] = []
    keys = [k for k in store.position_index.keys() if k[1] == pair_code]
    for trader_id, _ in keys:
        affected.append(recompute_position(store, trader_id, pair_code, current_trading_day))
    return affected


def _bucket_position_usd(
    store: Store, trader_id: str, pair_code: str, bucket: str,
    current_trading_day: str,
) -> Decimal:
    """Aggregate USD position for one (trader, pair, bucket).

    INTRADAY: today's BOOKED trades booked before 17:00 UTC.
    OVERNIGHT: today's BOOKED trades booked at/after 17:00 UTC plus any
               BOOKED trades whose trading_day is in a prior day.
    """
    pair_id = store.pair_index_by_code.get(pair_code)
    if pair_id is None:
        return ZERO
    pair = store.currency_pairs[pair_id]

    trades = _trades_for_position(store, trader_id, pair_code)
    included: list[dict] = []
    for trade in trades:
        if _trade_included_for_bucket(trade, bucket, current_trading_day):
            included.append(trade)
    included = _sorted_trades(included)

    signed = ZERO
    for trade in included:
        signed = signed + _signed_base_for_trade(trade)

    rate = base_in_usd_rate(store, pair)
    return round_half_up(signed * rate, 2)


def aggregate_bucket_usd_for_limit(
    store: Store, limit: dict, current_trading_day: str,
) -> Decimal:
    """Total absolute USD exposure that should be measured against `limit`.

    A limit with pair_code == None aggregates across all pairs the trader holds.
    """
    trader_id = limit["trader_id"]
    bucket = limit["bucket"]
    pair_code = limit.get("pair_code")
    if pair_code:
        return abs(_bucket_position_usd(store, trader_id, pair_code, bucket, current_trading_day))
    # Aggregate across all pairs the trader has positions in.
    pair_codes = {k[1] for k in store.position_index.keys() if k[0] == trader_id}
    total = ZERO
    for code in pair_codes:
        total = total + abs(_bucket_position_usd(store, trader_id, code, bucket, current_trading_day))
    return round_half_up(total, 2)


def recompute_limit_utilization(
    store: Store, limit: dict, current_trading_day: str,
) -> dict:
    """Recompute utilization_usd and utilization_pct for `limit`.

    PRD §2.4: 'incremented by exactly 1 on every successful mutation' — so
    we touch `updated_at` (cascades still bump that per §2.7) but we do NOT
    bump `version`, which is reserved for direct entity mutations
    (create/PATCH/state transition). Internal cascades from trade booking
    or quote arrival recompute derived fields without producing OCC drift.
    """
    util_usd = aggregate_bucket_usd_for_limit(store, limit, current_trading_day)
    cap = to_decimal(limit["notional_cap_usd"])
    override = to_decimal(limit.get("temporary_override_usd") or ZERO)
    effective = cap + override
    if effective <= ZERO:
        pct = Decimal("0")
    else:
        pct = round_half_up((util_usd / effective) * Decimal("100"), 2)
    limit["utilization_usd"] = util_usd
    limit["utilization_pct"] = pct
    limit["updated_at"] = now_iso()
    return limit


def _warning_status_from_pct(pct: Decimal) -> str:
    if pct >= BREACH_PCT:
        return "BREACH"
    if pct >= WARNING_PCT:
        return "WARNING"
    return "NORMAL"


def recompute_warning_status_for_trader(
    store: Store, trader_id: str, current_trading_day: str,
) -> None:
    """Recompute Position.warning_status for every position of this trader.

    A position's warning status is the worst (most severe) status across
    every Limit that gates it — i.e., the limit whose pair_code matches OR
    the aggregate limit (pair_code == None) for either INTRADAY or
    OVERNIGHT bucket.
    """
    trader_pairs = [k for k in store.position_index.keys() if k[0] == trader_id]
    # Pre-recompute every limit's utilisation so the cascade reflects truth.
    limits = [l for l in store.limits.values() if l["trader_id"] == trader_id]
    for limit in limits:
        recompute_limit_utilization(store, limit, current_trading_day)

    severity = {"NORMAL": 0, "WARNING": 1, "BREACH": 2}
    for trader_id_, pair_code in trader_pairs:
        if trader_id_ != trader_id:
            continue
        position = store.positions[store.position_index[(trader_id_, pair_code)]]
        worst = "NORMAL"
        for limit in limits:
            if limit.get("pair_code") not in (None, pair_code):
                continue
            status = _warning_status_from_pct(to_decimal(limit.get("utilization_pct") or 0))
            if severity[status] > severity[worst]:
                worst = status
        if position.get("warning_status") != worst:
            position["warning_status"] = worst
        position["updated_at"] = now_iso()


def projected_bucket_usd_with_trade(
    store: Store, trader_id: str, pair_code: str, side: str,
    notional_base: Decimal, bucket: str, current_trading_day: str,
    *, simulated_executed_at: str,
) -> Decimal:
    """Project absolute USD position in `bucket` if a new trade were added.

    Used for the priority-10 ERR_LIMIT_BREACH check at trade booking time.
    """
    pair_id = store.pair_index_by_code.get(pair_code)
    if pair_id is None:
        return ZERO
    pair = store.currency_pairs[pair_id]

    trades = _trades_for_position(store, trader_id, pair_code)
    # Simulate the new trade as an in-memory row.
    simulated = {
        "id": "zzz",
        "executed_at": simulated_executed_at,
        "trading_day": current_trading_day,
        "side": side,
        "notional_base": notional_base,
        "status": "BOOKED",
    }
    included = [
        t for t in trades
        if _trade_included_for_bucket(t, bucket, current_trading_day)
    ]
    if _trade_included_for_bucket(simulated, bucket, current_trading_day):
        included.append(simulated)
    included = _sorted_trades(included)

    signed = ZERO
    for trade in included:
        delta = to_decimal(trade["notional_base"]) if trade["side"] == "BUY" else -to_decimal(trade["notional_base"])
        signed = signed + delta
    rate = base_in_usd_rate(store, pair)
    return abs(round_half_up(signed * rate, 2))


def aggregate_counterparty_facing_usd(
    store: Store, counterparty_id: str,
    *, exclude_trade_id: Optional[str] = None,
) -> Decimal:
    """Sum of absolute USD notional of all BOOKED trades facing this counterparty.

    A simple aggregate-notional check; PRD doesn't specify trader-level
    netting for this gate, only "aggregate notional facing the counterparty".
    """
    total = ZERO
    for trade in store.trades.values():
        if trade["counterparty_id"] != counterparty_id:
            continue
        if trade["status"] != "BOOKED":
            continue
        if exclude_trade_id is not None and trade["id"] == exclude_trade_id:
            continue
        pair_code = trade["pair_code"]
        pair_id = store.pair_index_by_code.get(pair_code)
        if pair_id is None:
            continue
        pair = store.currency_pairs[pair_id]
        rate = base_in_usd_rate(store, pair)
        notional_usd = abs(to_decimal(trade["notional_base"]) * rate)
        total = total + notional_usd
    return round_half_up(total, 2)


def gross_and_net_exposure(store: Store, trader_id: str) -> tuple[Decimal, Decimal]:
    """§1.3 gross_exposure / net exposure for a trader."""
    positions = [
        p for p in store.positions.values()
        if p["trader_id"] == trader_id and to_decimal(p.get("net_base") or 0) != 0
    ]
    gross = ZERO
    for p in positions:
        gross = gross + abs(to_decimal(p.get("net_open_usd") or 0))
    gross = round_half_up(gross, 2)

    # Net: decompose each position into base-leg / quote-leg in USD terms,
    # accumulate per currency, then sum absolute values.
    legs: dict[str, Decimal] = {}
    for p in positions:
        pair_id = store.pair_index_by_code.get(p["pair_code"])
        if pair_id is None:
            continue
        pair = store.currency_pairs[pair_id]
        net_base = to_decimal(p["net_base"])
        base_usd = usd_rate_for_ccy(store, pair["base_ccy"]) or ZERO
        quote_usd = usd_rate_for_ccy(store, pair["quote_ccy"]) or ZERO
        mid = to_decimal(pair["mid_rate"])
        base_leg = net_base * base_usd
        quote_leg = -(net_base * mid * quote_usd)
        legs[pair["base_ccy"]] = legs.get(pair["base_ccy"], ZERO) + base_leg
        legs[pair["quote_ccy"]] = legs.get(pair["quote_ccy"], ZERO) + quote_leg

    net = ZERO
    for v in legs.values():
        net = net + abs(v)
    net = round_half_up(net, 2)
    return gross, net


def value_at_risk(store: Store, trader_id: str) -> Decimal:
    """§1.3 value_at_risk: per-position round-then-sum."""
    total = ZERO
    for p in store.positions.values():
        if p["trader_id"] != trader_id:
            continue
        if to_decimal(p.get("net_base") or 0) == 0:
            continue
        pair_id = store.pair_index_by_code.get(p["pair_code"])
        if pair_id is None:
            continue
        pair = store.currency_pairs[pair_id]
        exposure = abs(to_decimal(p["net_open_usd"]))
        vol = to_decimal(pair.get("daily_volatility") or 0)
        var_p = round_half_up(exposure * vol * Z_99, 2)
        total = total + var_p
    return round_half_up(total, 2)
