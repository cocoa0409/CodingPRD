"""Calculation rules per SCAFFOLD §1.3."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from config import (
    AGE_BIAS_THRESHOLD,
    AGGRESSIVE_MAX,
    ASSET_CLASSES,
    CONSERVATIVE_MAX,
    LONG_HORIZON_MAX,
    LONG_TERM_DAY_THRESHOLD,
    MID_HORIZON_MAX,
    MIN_HARVEST_THRESHOLD_CENTS,
    MODERATE_MAX,
    SHORT_HORIZON_MAX,
    W_EXP,
    W_GROW,
    W_LIQ,
    W_LOSS,
    W_VOL,
    WASH_WINDOW_DAYS,
)
from utils import (
    floor_date_utc,
    parse_iso,
    round_half_up_2dp,
    round_half_up_to_int,
    truncate_to_4dp,
)


# ── Risk scoring ────────────────────────────────────────────────────────────


def compute_risk_score(q1, q2, q3, q4, q5, scoring_method, client_age):
    """Return (raw_score:int, assigned_band:str).

    STANDARD: raw = q1 + q2 + q3 + (6 - q4) + q5
    AGE_ADJUSTED (applies only when scoring_method == AGE_ADJUSTED AND client_age >= 55):
                 same as STANDARD but q3 contribution becomes (6 - q3).
    """
    use_age_adjusted = (
        scoring_method == "AGE_ADJUSTED"
        and client_age is not None
        and client_age >= AGE_BIAS_THRESHOLD
    )

    q3_term = (6 - q3) if use_age_adjusted else q3
    raw = (
        W_LOSS * q1
        + W_VOL * q2
        + W_GROW * q3_term
        + W_LIQ * (6 - q4)
        + W_EXP * q5
    )

    if raw <= CONSERVATIVE_MAX:
        band = "CONSERVATIVE"
    elif raw <= MODERATE_MAX:
        band = "MODERATE"
    else:
        band = "AGGRESSIVE"
    return raw, band


def derive_horizon_band(time_horizon_years: int) -> str:
    if time_horizon_years is None:
        return None
    if 1 <= time_horizon_years <= SHORT_HORIZON_MAX:
        return "SHORT"
    if time_horizon_years <= MID_HORIZON_MAX:
        return "MID"
    if time_horizon_years <= LONG_HORIZON_MAX:
        return "LONG"
    return None


def pick_model_portfolio(store, risk_band, horizon_band):
    """Return the active ModelPortfolio matching the bands; tie-break: lower id ASC."""
    if risk_band is None or horizon_band is None:
        return None
    candidates = [
        m for m in store.model_portfolios.values()
        if m.get("is_active")
        and m["risk_band"] == risk_band
        and m["horizon_band"] == horizon_band
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda m: m["id"])
    return candidates[0]


# ── Realized gain / loss ────────────────────────────────────────────────────


def select_lots_for_sell(store, position_id, method, specific_lot_id):
    """Return the ordered list of lots that will be consumed (immutable view)."""
    if method == "SPECIFIC_LOT":
        lot = store.lots.get(specific_lot_id)
        if lot is None or lot.get("position_id") != position_id:
            return []
        if lot["status"] == "CLOSED" or lot["shares_remaining"] <= 0:
            return []
        return [lot]
    # FIFO: OPEN ∪ PARTIALLY_CLOSED, sorted by acquired_at ASC, id ASC
    pool = [
        l for l in store.lots.values()
        if l["position_id"] == position_id
        and l["status"] in ("OPEN", "PARTIALLY_CLOSED")
        and l["shares_remaining"] > 0
    ]
    pool.sort(key=lambda l: (l["acquired_at"], l["id"]))
    return pool


def consume_lots_and_compute_pnl(lots_in_order, requested_shares, execution_price_cents):
    """Apply realized-gain-loss with per-trade rounding pass.

    Mutates each consumed lot's shares_remaining and status. Returns
    (gross_proceeds_cents, total_basis_cents, realized_gain_loss_cents,
     consumed_pairs) where consumed_pairs is a list of (lot_id, shares_consumed).
    """
    remaining = Decimal(str(requested_shares))
    total_basis_cents = 0
    consumed_pairs = []
    for lot in lots_in_order:
        if remaining <= 0:
            break
        shares_remaining = Decimal(str(lot["shares_remaining"]))
        take = min(remaining, shares_remaining)
        if take <= 0:
            continue
        # Lot-level multiplication kept in raw cent arithmetic; rounding only at trade totals.
        product = take * Decimal(str(lot["adjusted_unit_cost_cents"]))
        total_basis_cents += round_half_up_to_int(product)
        # Mutate the lot.
        new_lot_remaining = shares_remaining - take
        if new_lot_remaining <= 0:
            lot["shares_remaining"] = 0
            lot["status"] = "CLOSED"
        else:
            lot["shares_remaining"] = float(new_lot_remaining)
            lot["status"] = "PARTIALLY_CLOSED"
        consumed_pairs.append((lot["id"], float(take)))
        # `remaining` is the trade's still-unsatisfied share count.
        remaining = remaining - take
    gross_proceeds_cents = round_half_up_to_int(
        Decimal(str(requested_shares)) * Decimal(str(execution_price_cents))
    )
    realized_gain_loss_cents = gross_proceeds_cents - total_basis_cents
    return gross_proceeds_cents, total_basis_cents, realized_gain_loss_cents, consumed_pairs


# ── Wash sale basis adjustment ──────────────────────────────────────────────


def find_wash_sale_candidates(store, sell_trade, group_id, sell_date):
    """Return BUY candidate trades within the ±WASH_WINDOW_DAYS window, sorted by executed_at ASC, id ASC.

    Filters:
      - same account_id
      - side == BUY
      - status == SETTLED
      - security's substantially_identical_group_id == group_id
      - floor_date(executed_at) within [sell_date - 30, sell_date + 30]
    """
    window_start = sell_date - timedelta(days=WASH_WINDOW_DAYS)
    window_end = sell_date + timedelta(days=WASH_WINDOW_DAYS)
    out = []
    for t in store.trades.values():
        if t["account_id"] != sell_trade["account_id"]:
            continue
        if t["side"] != "BUY":
            continue
        if t["status"] != "SETTLED":
            continue
        sec = store.securities.get(t["security_id"])
        if not sec:
            continue
        if sec["substantially_identical_group_id"] != group_id:
            continue
        ex = t.get("executed_at")
        if not ex:
            continue
        ex_dt = parse_iso(ex)
        ex_date = floor_date_utc(ex_dt)
        if window_start <= ex_date <= window_end:
            out.append(t)
    out.sort(key=lambda t: (t.get("executed_at") or "", t["id"]))
    return out


def has_wash_sale_blocker(store, account_id, security_id, now_dt):
    """Pre-flight: is there a SELL on the same account, same group, settled
    within the last WASH_WINDOW_DAYS calendar days?
    """
    sec = store.securities.get(security_id)
    if not sec:
        return False
    group_id = sec["substantially_identical_group_id"]
    now_date = floor_date_utc(now_dt)
    cutoff = now_date - timedelta(days=WASH_WINDOW_DAYS)
    for t in store.trades.values():
        if t["account_id"] != account_id:
            continue
        if t["side"] != "SELL":
            continue
        if t["status"] != "SETTLED":
            continue
        s2 = store.securities.get(t["security_id"])
        if not s2:
            continue
        if s2["substantially_identical_group_id"] != group_id:
            continue
        ex = t.get("executed_at")
        if not ex:
            continue
        ex_date = floor_date_utc(parse_iso(ex))
        if cutoff <= ex_date <= now_date:
            # Only counts as a wash-sale blocker when that SELL realised a loss.
            if (t.get("realized_gain_loss_cents") or 0) < 0:
                return True
    return False


# ── Drift recompute ─────────────────────────────────────────────────────────


def recompute_account_drift(store, account):
    """Update account.max_drift_pct in place using §3.8 formula."""
    model_id = account.get("model_portfolio_id")
    if not model_id:
        # No model assigned yet — drift is 0.
        account["max_drift_pct"] = 0.00
        return 0.00
    model = store.model_portfolios.get(model_id)
    if not model:
        account["max_drift_pct"] = 0.00
        return 0.00
    # Refresh position market values first (in case price changed).
    for p in store.positions.values():
        if p["account_id"] != account["id"]:
            continue
        sec = store.securities.get(p["security_id"])
        if sec:
            p["market_value_cents"] = round_half_up_to_int(
                Decimal(str(p["shares"])) * Decimal(str(sec["last_price_cents"]))
            )

    cash_cents = Decimal(str(account.get("cash_balance_cents", 0)))
    positions = [p for p in store.positions.values() if p["account_id"] == account["id"]]
    total_mv = sum((Decimal(str(p["market_value_cents"])) for p in positions), Decimal(0)) + cash_cents
    if total_mv <= 0:
        account["max_drift_pct"] = 0.00
        return 0.00

    # Aggregate by asset class.
    class_mv = {c: Decimal(0) for c in ASSET_CLASSES}
    class_mv["CASH"] = cash_cents
    for p in positions:
        sec = store.securities.get(p["security_id"])
        if not sec:
            continue
        ac = sec["asset_class"]
        class_mv[ac] = class_mv.get(ac, Decimal(0)) + Decimal(str(p["market_value_cents"]))

    target = model["target_allocation"]
    max_drift = Decimal(0)
    for c in ASSET_CLASSES:
        current_weight = class_mv[c] / total_mv
        target_weight = Decimal(str(target.get(c, 0)))
        drift = abs(current_weight - target_weight) * Decimal(100)
        if drift > max_drift:
            max_drift = drift
    max_drift_2dp = round_half_up_2dp(max_drift)
    account["max_drift_pct"] = max_drift_2dp
    return max_drift_2dp


# ── Harvest opportunity detection ───────────────────────────────────────────


def pick_replacement_security(store, held_security):
    """Top correlated investable security outside the held group with a CorrelationLink."""
    held_group = held_security["substantially_identical_group_id"]
    held_id = held_security["id"]
    # Build set of partner security ids via correlation links.
    linked = {}  # other_id -> correlation value
    for link in store.correlation_links.values():
        a, b, corr = link["security_a_id"], link["security_b_id"], link["correlation"]
        if a == held_id:
            linked[b] = corr
        elif b == held_id:
            linked[a] = corr
    candidates = []
    for sid, corr in linked.items():
        sec = store.securities.get(sid)
        if not sec or not sec.get("is_investable"):
            continue
        if sec["substantially_identical_group_id"] == held_group:
            continue
        candidates.append((corr, sec["ticker"], sec["id"]))
    if not candidates:
        return None
    # correlation DESC, ticker ASC
    candidates.sort(key=lambda x: (-x[0], x[1]))
    return candidates[0][2]


# ── 1099-B holding period & classification ──────────────────────────────────


def compute_trade_holding_period_days(store, trade):
    """Weighted average of (sell_date - lot.acquired_at) days over consumed lots,
    weighted by shares_consumed. The consumed-lot info is stored on the trade
    as `consumed_lots`: list of {lot_id, shares}.
    """
    if not trade.get("executed_at"):
        return 0
    sell_dt = parse_iso(trade["executed_at"])
    sell_date = floor_date_utc(sell_dt)
    consumed = trade.get("consumed_lots") or []
    if not consumed:
        return 0
    total_shares = Decimal(0)
    weighted_days = Decimal(0)
    for item in consumed:
        lot = store.lots.get(item["lot_id"])
        if not lot:
            continue
        acquired = parse_iso(lot["acquired_at"])
        acquired_date = floor_date_utc(acquired)
        days = Decimal((sell_date - acquired_date).days)
        shares = Decimal(str(item["shares"]))
        weighted_days += days * shares
        total_shares += shares
    if total_shares == 0:
        return 0
    avg = weighted_days / total_shares
    return float(avg)


def classify_trade_term(store, trade) -> str:
    days = compute_trade_holding_period_days(store, trade)
    return "SHORT" if days <= LONG_TERM_DAY_THRESHOLD else "LONG"


# ── Dividend reinvest ──────────────────────────────────────────────────────


def compute_reinvest_shares(amount_cents: int, price_cents: int) -> float:
    """Fractional share count truncated to 4 dp."""
    if price_cents is None or price_cents <= 0:
        return 0.0
    raw = Decimal(amount_cents) / Decimal(price_cents)
    return truncate_to_4dp(raw)
