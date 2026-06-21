"""30-day taker/maker volume and fee-tier derivation (§3.9, calc account_30d_taker_volume)."""
from datetime import timedelta

from numeric import D, round_usd

WINDOW_DAYS = 30
TIER_ORDER = ["TIER_BASE", "TIER_1", "TIER_2", "TIER_3"]


def _window_start(store):
    return store.clock.now() - timedelta(days=WINDOW_DAYS)


def _trade_notional_usd_rounded(trade):
    # Recompute notional in USD from stored components, round per-trade to 2dp.
    return round_usd(D(trade["notional_usd"]))


def taker_volume_30d(store, account_id):
    start = _window_start(store)
    now = store.clock.now()
    total = D(0)
    for t in store.trades.values():
        taker = store.orders.get(t["taker_order_id"])
        if taker is None or taker["account_id"] != account_id:
            continue
        ex = t["executed_at"]
        if ex > start and ex <= now:
            total += _trade_notional_usd_rounded(t)
    return round_usd(total)


def maker_volume_30d(store, account_id):
    start = _window_start(store)
    now = store.clock.now()
    total = D(0)
    for t in store.trades.values():
        maker = store.orders.get(t["maker_order_id"])
        if maker is None or maker["account_id"] != account_id:
            continue
        ex = t["executed_at"]
        if ex > start and ex <= now:
            total += _trade_notional_usd_rounded(t)
    return round_usd(total)


def fee_tier_for(store, taker_volume):
    """Tier whose min_taker_volume_30d_usd is the highest inclusive bound <= volume."""
    vol = D(taker_volume)
    best = None
    best_min = None
    for f in store.fee_schedules.values():
        m = D(f["min_taker_volume_30d_usd"])
        if vol >= m:
            if best_min is None or m > best_min:
                best_min = m
                best = f["tier_name"]
    # When no schedule qualifies (e.g. none configured), default to base.
    return best if best is not None else "TIER_BASE"


def fee_bps_for_account(store, account_id, side):
    """Return (maker_or_taker bps) for the account's current tier."""
    vol = taker_volume_30d(store, account_id)
    tier = fee_tier_for(store, vol)
    sched = store.fee_schedule_by_tier(tier)
    if sched is None:
        return D(0)
    return D(sched["maker_fee_bps"]) if side == "maker" else D(sched["taker_fee_bps"])
