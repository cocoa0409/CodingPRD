"""Business engine: state transitions, cascades, time-gate sweeps.

Centralises mutations that touch multiple entities (PDT cascade, ACAT
posture cascade, portfolio equity recompute, day-trade pairing) so a
single touch policy applies everywhere — every changed row bumps its
own `updated_at` and `version` per PRD §2.4.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import config as cfg
from db import store
from services.calculations import (
    acat_expected_completion,
    trade_date_utc,
)
from utils import (
    add_business_days,
    business_days_between,
    is_business_day,
    parse_iso_date,
    subtract_business_days,
)


# ── Common touch policy ────────────────────────────────────────────────────


def touch(entity: dict, now: datetime) -> None:
    """Apply the §2.4 mutation contract: updated_at + version bump.

    Use this on every row that is mutated by a successful operation,
    including children touched by a cascade. KYCSubmission and DayTrade
    are append-only and never reach this function.
    """
    entity["updated_at"] = now
    entity["version"] = entity.get("version", 0) + 1


# ── Portfolio equity (calc 6 / PRD §3.7) ───────────────────────────────────


def recompute_equity(account: dict) -> None:
    """Mark-to-market: cash + Σ (per-symbol net qty × last EQUITY price).

    Only EQUITY orders contribute; OPTION fills are ignored. Per-symbol
    contributions are computed independently and then summed.
    """
    cash = account["cash_balance_cents"]
    account_id = account["id"]

    by_symbol: dict[str, list[dict]] = {}
    for o in store.orders.values():
        if o["account_id"] != account_id:
            continue
        if o["status"] != cfg.ORDER_FILLED:
            continue
        if o["instrument_type"] != cfg.INSTRUMENT_EQUITY:
            continue
        by_symbol.setdefault(o["symbol"], []).append(o)

    market_value = 0
    for symbol, rows in by_symbol.items():
        net_qty = 0
        last_price = None
        last_filled_at = None
        for r in rows:
            qty = r["quantity"]
            if r["side"] == cfg.SIDE_BUY:
                net_qty += qty
            else:
                net_qty -= qty
            fa = r.get("filled_at")
            fp = r.get("fill_price_cents")
            if fp is None or fa is None:
                continue
            if last_filled_at is None or fa > last_filled_at:
                last_filled_at = fa
                last_price = fp
        if last_price is None or net_qty <= 0:
            continue
        market_value += net_qty * last_price

    account["equity_value_cents"] = cash + market_value


# ── Day-trade pairing + PDT check (calcs 3-4 / PRD §3.4) ───────────────────


def _trade_dates_in_pdt_window(today_utc):
    """Return the inclusive 5-business-day window ending today (UTC)."""
    window_start = subtract_business_days(today_utc, cfg.PDT_WINDOW_BUSINESS_DAYS - 1)
    return window_start, today_utc


def pair_day_trade_if_any(filled_order: dict, now: datetime) -> dict | None:
    """If `filled_order` closes an opposite-side same-day fill, insert a
    DayTrade and mark both legs as opened_for_day_trade. Returns the
    inserted DayTrade row (or None if no pairing).
    """
    account_id = filled_order["account_id"]
    symbol = filled_order["symbol"]
    self_side = filled_order["side"]
    self_trade_date = trade_date_utc(filled_order["filled_at"])

    candidates = []
    for o in store.orders.values():
        if o["id"] == filled_order["id"]:
            continue
        if o["account_id"] != account_id:
            continue
        if o["symbol"] != symbol:
            continue
        if o["status"] != cfg.ORDER_FILLED:
            continue
        if o.get("opened_for_day_trade"):
            continue
        if o["side"] == self_side:
            continue
        fa = o.get("filled_at")
        if fa is None:
            continue
        if trade_date_utc(fa) != self_trade_date:
            continue
        candidates.append(o)

    if not candidates:
        return None

    candidates.sort(key=lambda r: (r["filled_at"], r["id"]))
    opener = candidates[0]

    opener["opened_for_day_trade"] = True
    touch(opener, now)
    filled_order["opened_for_day_trade"] = True
    # filled_order's touch happens in the caller after fill bookkeeping.

    from utils import new_uuid

    dt_id = new_uuid()
    dt = {
        "id": dt_id,
        "account_id": account_id,
        "symbol": symbol,
        "opening_order_id": opener["id"],
        "closing_order_id": filled_order["id"],
        "trade_date": self_trade_date,
        "created_at": now,
    }
    store.day_trades[dt_id] = dt
    return dt


def count_day_trades_in_window(account_id: str, today_utc) -> int:
    window_start, window_end = _trade_dates_in_pdt_window(today_utc)
    count = 0
    for d in store.day_trades.values():
        if d["account_id"] != account_id:
            continue
        td = parse_iso_date(d["trade_date"])
        if td is None:
            continue
        if window_start <= td <= window_end:
            count += 1
    return count


def evaluate_pdt(account: dict, now: datetime) -> bool:
    """Run pdt_flag_check after a DayTrade row is inserted.

    If count(DayTrade in window) >= 4 AND equity < PDT_FLOOR, raise the
    PDT freeze and cascade-cancel non-terminal Orders + reject
    non-terminal OptionsApprovals. Returns True when the freeze fired.
    """
    today_utc = now.astimezone(timezone.utc).date()
    count = count_day_trades_in_window(account["id"], today_utc)
    if count >= cfg.PDT_TRADE_THRESHOLD and account["equity_value_cents"] < cfg.PDT_EQUITY_FLOOR_CENTS:
        if not account["pdt_flag"] or account["trading_posture"] != cfg.POSTURE_PDT_FROZEN:
            account["pdt_flag"] = True
            account["pdt_flagged_at"] = now
            account["trading_posture"] = cfg.POSTURE_PDT_FROZEN
            touch(account, now)
            _cascade_pdt_cancellations(account["id"], now)
            return True
    return False


def _cascade_pdt_cancellations(account_id: str, now: datetime) -> None:
    """Cancel every non-terminal Order; reject every non-terminal
    OptionsApproval with reason='PDT_FREEZE'. Each touched row receives
    its own updated_at + version bump (PRD §2.4)."""
    for o in store.orders.values():
        if o["account_id"] == account_id and o["status"] in cfg.ORDER_OPEN:
            o["status"] = cfg.ORDER_CANCELLED
            touch(o, now)
    for oa in store.options_approvals.values():
        if oa["account_id"] == account_id and oa["status"] in cfg.OA_NON_TERMINAL:
            oa["status"] = cfg.OA_REJECTED
            oa["review_notes"] = "PDT_FREEZE"
            touch(oa, now)


def would_create_fourth_day_trade(account: dict, symbol: str, side: str, now: datetime) -> bool:
    """Quick check used at order submission to enforce
    ERR_PDT_EQUITY_BELOW_MINIMUM once the account is already flagged.

    If pdt_flag is true and equity is still below the floor, any order
    whose fill could plausibly create a 4th-or-later day trade in the
    rolling window is rejected. The most conservative check (and the
    one the scaffold's prose implies) is: if there is at least one
    same-symbol opposite-side filled order on today's UTC date that is
    not yet paired, this order's fill would create a new DayTrade. Even
    short of that, with 3+ DayTrades already in window, any further day
    trade would cross the threshold. We keep the check inclusive: if
    the account is already at >= PDT_THRESHOLD - 1 day trades in
    window, the next round-trip would make the count >= threshold.
    """
    today_utc = now.astimezone(timezone.utc).date()
    count = count_day_trades_in_window(account["id"], today_utc)
    if count >= cfg.PDT_TRADE_THRESHOLD:
        # Already at or past threshold; any further order is blocked.
        return True
    if count >= cfg.PDT_TRADE_THRESHOLD - 1:
        # One more day trade would trip the limit. Check whether an
        # opposite-side same-symbol filled order exists today (the
        # condition for this new order to round-trip on fill).
        today_str = today_utc.isoformat()
        for o in store.orders.values():
            if o["account_id"] != account["id"]:
                continue
            if o["symbol"] != symbol:
                continue
            if o["status"] != cfg.ORDER_FILLED:
                continue
            if o.get("opened_for_day_trade"):
                continue
            if o["side"] == side:
                continue
            fa = o.get("filled_at")
            if fa is None:
                continue
            if trade_date_utc(fa) == today_str:
                return True
    return False


# ── ACAT time-gate evaluation (PRD §3.5 / §3.8) ────────────────────────────


def recompute_acat_business_days_elapsed(t: dict, now: datetime) -> int:
    elapsed = business_days_between(t["initiated_at"], now)
    t["business_days_elapsed"] = elapsed
    return elapsed


def apply_acat_time_gates(now: datetime) -> None:
    """Run after every clock-advance and every sweep.

    Transitions:
      VALIDATED → IN_TRANSIT  when business_days_elapsed >= 1
      IN_TRANSIT → COMPLETED  when now() >= expected_completion_at
    Plus the post-completion cash/equity adjustments and outbound
    posture cascade (PRD §3.5).
    """
    # Snapshot to avoid mutating during iteration.
    transfers = list(store.acat_transfers.values())
    transfers.sort(key=lambda t: t["initiated_at"])

    for t in transfers:
        # Always refresh business_days_elapsed so the view reflects time.
        if t["status"] in (cfg.ACAT_VALIDATED, cfg.ACAT_IN_TRANSIT):
            recompute_acat_business_days_elapsed(t, now)

        if t["status"] == cfg.ACAT_VALIDATED and t["business_days_elapsed"] >= 1:
            t["status"] = cfg.ACAT_IN_TRANSIT
            touch(t, now)

        if (
            t["status"] == cfg.ACAT_IN_TRANSIT
            and t.get("expected_completion_at") is not None
            and now >= t["expected_completion_at"]
        ):
            t["status"] = cfg.ACAT_COMPLETED
            t["completed_at"] = now
            touch(t, now)
            _apply_acat_completion_effects(t, now)


def _apply_acat_completion_effects(t: dict, now: datetime) -> None:
    """Apply cash/equity adjustments and outbound posture revert."""
    account = store.accounts.get(t["account_id"])
    if account is None:
        return
    value = t["requested_value_cents"]
    if t["direction"] == cfg.ACAT_INBOUND:
        account["cash_balance_cents"] += value
        recompute_equity(account)
        touch(account, now)
    else:
        account["cash_balance_cents"] -= value
        recompute_equity(account)
        touch(account, now)
        # Revert TRANSFER_LOCKED to OPEN iff no other non-terminal
        # OUTBOUND transfer remains for this account.
        if account["trading_posture"] == cfg.POSTURE_TRANSFER_LOCKED:
            still_locked = False
            for other in store.acat_transfers.values():
                if other["id"] == t["id"]:
                    continue
                if (
                    other["account_id"] == t["account_id"]
                    and other["direction"] == cfg.ACAT_OUTBOUND
                    and other["status"] in (cfg.ACAT_VALIDATED, cfg.ACAT_IN_TRANSIT)
                ):
                    still_locked = True
                    break
            if not still_locked:
                account["trading_posture"] = cfg.POSTURE_OPEN
                touch(account, now)


# ── Order cash adjustment on fill ──────────────────────────────────────────


def apply_fill_cash_adjustment(order: dict, account: dict, fill_price: int) -> None:
    """Cash debit on BUY, credit on SELL. PRD §3.3.

    Only EQUITY fills move cash by quantity * fill_price; OPTION orders
    are excluded from the simple equity/cash model per PRD §3.7.
    The PRD's prose says "signed quantity times fill price" generally,
    so OPTION fills also adjust cash but do not contribute to equity
    market value.
    """
    delta = order["quantity"] * fill_price
    if order["side"] == cfg.SIDE_BUY:
        account["cash_balance_cents"] -= delta
    else:
        account["cash_balance_cents"] += delta


# ── ACAT validation completion-eta calc ────────────────────────────────────


def stamp_acat_validated(t: dict, now: datetime) -> None:
    t["status"] = cfg.ACAT_VALIDATED
    t["expected_completion_at"] = acat_expected_completion(t["initiated_at"])
    touch(t, now)
