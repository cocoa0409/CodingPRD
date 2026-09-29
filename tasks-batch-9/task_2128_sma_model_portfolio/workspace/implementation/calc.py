"""Calculation rules (scaffold 1.3 / PRD 2.8, 2.10, 3.5-3.9).

Every constant here is copied verbatim from the scaffold's `constants` blocks.
"""

from datetime import timedelta
from fractions import Fraction

from core import (
    ApiError, clock, db, new_row, round_half_up, touch,
)

# --- constants -------------------------------------------------------------
TOTAL_BPS = 10000
CAP_PASSES = 3
MIN_CASH_RESERVE_CENTS = 10000
MIN_TRADE_CENTS = 5000
WASH_WINDOW_DAYS = 30
TIER1_CEILING_CENTS = 25000000
TIER2_CEILING_CENTS = 100000000
TIER2_DISCOUNT_BPS = 10
TIER3_DISCOUNT_BPS = 20
DAYS_IN_YEAR = 365
PLATFORM_FEE_BPS = 500
PAYMENT_TERM_DAYS = 30


# ---------------------------------------------------------------------------
# Position / valuation helpers
# ---------------------------------------------------------------------------
def account_lots(account_id, security_id=None, status="OPEN"):
    out = []
    for lot in db.tax_lots.values():
        if lot["account_id"] != account_id:
            continue
        if status is not None and lot["status"] != status:
            continue
        if security_id is not None and lot["security_id"] != security_id:
            continue
        out.append(lot)
    return out


def settled_shares(account_id, security_id):
    return sum(l["shares_open"] for l in account_lots(account_id, security_id))


def market_value_cents(account):
    total = account["cash_cents"]
    for lot in account_lots(account["id"]):
        sec = db.securities.get(lot["security_id"])
        if sec is not None:
            total += lot["shares_open"] * sec["last_price_cents"]
    return total


def account_restrictions(account_id, active_only=True):
    out = []
    for r in db.account_restrictions.values():
        if r["account_id"] != account_id:
            continue
        if active_only and r["status"] != "ACTIVE":
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# effective_sleeve_weights (scaffold 1.3 / PRD 3.5 stage one)
# ---------------------------------------------------------------------------
def effective_sleeve_weights(account, model_version):
    sleeves = list(model_version["sleeves"]) if model_version else []
    restrictions = account_restrictions(account["id"])

    excluded = set()
    restriction_caps = {}
    for r in restrictions:
        if r["restriction_type"] in ("DO_NOT_BUY", "DO_NOT_HOLD"):
            excluded.add(r["security_id"])
        elif r["restriction_type"] == "MAX_POSITION" and r.get("max_position_bps") is not None:
            prior = restriction_caps.get(r["security_id"])
            cap = r["max_position_bps"]
            restriction_caps[r["security_id"]] = cap if prior is None else min(prior, cap)

    base = {}
    cap = {}
    for sleeve in sleeves:
        sid = sleeve["security_id"]
        base[sid] = sleeve["target_weight_bps"]
        sleeve_cap = sleeve.get("max_position_bps")
        if sleeve_cap is None:
            sleeve_cap = TOTAL_BPS
        cap[sid] = min(sleeve_cap, restriction_caps.get(sid, TOTAL_BPS))

    eff = {}
    pinned = set()
    for sid in base:
        if sid in excluded:
            eff[sid] = 0
            pinned.add(sid)

    for _ in range(CAP_PASSES):
        free = sorted([s for s in base if s not in pinned], key=_ticker_of)
        if not free:
            break
        residual = TOTAL_BPS - sum(eff[s] for s in pinned)
        pool = sum(base[s] for s in free)
        if pool <= 0:
            for s in free:
                eff[s] = 0
            break
        for s in free:
            eff[s] = (residual * base[s]) // pool
        remainder = residual - sum(eff[s] for s in free)
        for k in range(remainder):
            eff[free[k % len(free)]] += 1
        breached = [s for s in free if eff[s] > cap[s]]
        if not breached:
            break
        for s in breached:
            eff[s] = cap[s]
            pinned.add(s)

    cash_target_bps = TOTAL_BPS - sum(eff.values())
    return eff, cash_target_bps


def _ticker_of(security_id):
    sec = db.securities.get(security_id)
    return sec["ticker"] if sec else ""


# ---------------------------------------------------------------------------
# trade_order_generation (scaffold 1.3 / PRD 3.5 stage two)
# ---------------------------------------------------------------------------
def generate_trade_orders(account, model_version, source):
    eff, _cash_target = effective_sleeve_weights(account, model_version)

    mv = market_value_cents(account)
    cash_reserve = max(MIN_CASH_RESERVE_CENTS,
                       (mv * account["cash_reserve_bps"]) // TOTAL_BPS)
    investable = mv - cash_reserve

    generation_set = set()
    if model_version:
        for sleeve in model_version["sleeves"]:
            generation_set.add(sleeve["security_id"])
    for lot in account_lots(account["id"]):
        if lot["shares_open"] > 0:
            generation_set.add(lot["security_id"])

    walk = sorted(generation_set, key=_ticker_of)

    pending = []
    seq = account["next_order_sequence"]
    for sid in walk:
        sec = db.securities.get(sid)
        if sec is None:
            continue
        weight = eff.get(sid, 0)
        cents = (investable * weight) // TOTAL_BPS
        target_shares = cents // sec["last_price_cents"]
        current = settled_shares(account["id"], sid)
        delta = target_shares - current
        if abs(delta) * sec["last_price_cents"] < MIN_TRADE_CENTS:
            continue
        pending.append({
            "security_id": sid,
            "side": "BUY" if delta > 0 else "SELL",
            "shares": abs(delta),
            "target_shares": target_shares,
            "effective_weight_bps": weight,
            "sequence_number": seq,
        })
        seq += 1

    if not pending:
        raise ApiError("ERR_NO_TRADES_GENERATED",
                       "The generator produced no tradable delta.")

    created = []
    for spec in pending:
        order = new_row(
            account_id=account["id"],
            security_id=spec["security_id"],
            model_version_id=model_version["id"],
            block_id=None,
            sequence_number=spec["sequence_number"],
            side=spec["side"],
            shares=spec["shares"],
            status="PROPOSED",
            source=source,
            target_shares=spec["target_shares"],
            effective_weight_bps=spec["effective_weight_bps"],
            allocated_shares=0,
            fill_price_cents=None,
        )
        db.trade_orders[order["id"]] = order
        created.append(order)
    account["next_order_sequence"] = seq
    return created


# ---------------------------------------------------------------------------
# account_drift_bps (scaffold 1.3 / PRD 3.6)
# ---------------------------------------------------------------------------
def drift_positions(account, basis):
    positions = {}
    for lot in account_lots(account["id"]):
        positions[lot["security_id"]] = positions.get(lot["security_id"], 0) + lot["shares_open"]
    cash = account["cash_cents"]

    if basis == "TRADE_DATE":
        for order in db.trade_orders.values():
            if order["account_id"] != account["id"]:
                continue
            if order["status"] not in ("PROPOSED", "BLOCKED"):
                continue
            sec = db.securities.get(order["security_id"])
            if sec is None:
                continue
            sid = order["security_id"]
            if order["side"] == "BUY":
                positions[sid] = positions.get(sid, 0) + order["shares"]
                cash -= order["shares"] * sec["last_price_cents"]
            else:
                positions[sid] = positions.get(sid, 0) - order["shares"]
                cash += order["shares"] * sec["last_price_cents"]
    return positions, cash


def evaluate_drift(account, basis):
    positions, cash = drift_positions(account, basis)

    model_version = None
    if account.get("current_model_version_id"):
        model_version = db.model_versions.get(account["current_model_version_id"])
    eff, _cash_target = effective_sleeve_weights(account, model_version)

    valuation = cash
    for sid, shares in positions.items():
        sec = db.securities.get(sid)
        if sec is not None:
            valuation += shares * sec["last_price_cents"]

    scan = set()
    if model_version:
        for sleeve in model_version["sleeves"]:
            scan.add(sleeve["security_id"])
    for sid, shares in positions.items():
        if shares != 0:
            scan.add(sid)

    drift = 0
    for sid in scan:
        sec = db.securities.get(sid)
        price = sec["last_price_cents"] if sec else 0
        shares = positions.get(sid, 0)
        if valuation == 0:
            actual_bps = 0
        else:
            actual_bps = round_half_up(shares * price * TOTAL_BPS, valuation)
        deviation = abs(actual_bps - eff.get(sid, 0))
        if deviation > drift:
            drift = deviation
    return drift


# ---------------------------------------------------------------------------
# block_pro_rata_allocation (scaffold 1.3 / PRD 3.7)
# ---------------------------------------------------------------------------
def pro_rata_allocation(filled_shares, orders):
    requested = sum(o["shares"] for o in orders)
    if requested <= 0:
        raise ApiError("ERR_INVALID_STATE", "The block has no participating orders.")
    alloc = {}
    for o in orders:
        alloc[o["id"]] = (filled_shares * o["shares"]) // requested
    remainder = filled_shares - sum(alloc.values())
    ordered = sorted(orders, key=lambda o: (-o["shares"], o["created_at"], o["_seq"]))
    for k in range(remainder):
        alloc[ordered[k % len(ordered)]["id"]] += 1
    return alloc


# ---------------------------------------------------------------------------
# hifo_disposal_ledger (scaffold 1.3 / PRD 3.7)
# ---------------------------------------------------------------------------
def hifo_candidates(account_id, security_id):
    lots = [l for l in db.tax_lots.values()
            if l["account_id"] == account_id
            and l["security_id"] == security_id
            and l["status"] == "OPEN"
            and l["shares_open"] > 0]
    lots.sort(key=lambda l: (-Fraction(l["cost_basis_cents"], l["shares_open"]),
                             l["created_at"], l["_seq"]))
    return lots


def hifo_plan(account_id, security_id, shares, price_cents):
    """Read-only HIFO walk.  Raises ERR_INSUFFICIENT_SHARES when short."""
    remaining = shares
    plan = []
    for lot in hifo_candidates(account_id, security_id):
        if remaining == 0:
            break
        take = min(lot["shares_open"], remaining)
        basis = round_half_up(lot["cost_basis_cents"] * take, lot["shares_open"])
        realized = take * price_cents - basis
        plan.append({"lot": lot, "take": take, "basis": basis, "realized": realized,
                     "split": take < lot["shares_open"]})
        remaining -= take
    if remaining > 0:
        raise ApiError("ERR_INSUFFICIENT_SHARES",
                       "The account does not hold enough open shares.")
    return plan


def plan_loss_figures(plan):
    target_loss = sum(step["realized"] for step in plan)
    proposed_loss = abs(sum(step["realized"] for step in plan if step["realized"] < 0))
    return target_loss, proposed_loss


def apply_hifo_plan(account, plan, closing_trade_order_id=None):
    """Mutating half of the HIFO walk.  Returns the list of CLOSED rows."""
    now = clock()
    closed_rows = []
    for step in plan:
        lot = step["lot"]
        take = step["take"]
        basis = step["basis"]
        realized = step["realized"]
        if not step["split"]:
            lot["status"] = "CLOSED"
            lot["shares_closed"] = take
            lot["shares_open"] = 0
            lot["realized_gain_cents"] = realized
            lot["close_date"] = now
            lot["closing_trade_order_id"] = closing_trade_order_id
            if realized < 0:
                lot["wash_window_start"] = now - timedelta(days=WASH_WINDOW_DAYS)
                lot["wash_window_end"] = now + timedelta(days=WASH_WINDOW_DAYS)
            touch(lot)
            closed_rows.append(lot)
        else:
            slice_row = new_row(
                account_id=lot["account_id"],
                security_id=lot["security_id"],
                parent_tax_lot_id=lot["id"],
                opening_trade_order_id=None,
                closing_trade_order_id=closing_trade_order_id,
                sequence_number=account["next_order_sequence"],
                origin=lot["origin"],
                open_date=lot["open_date"],
                shares_open=0,
                shares_closed=take,
                cost_basis_cents=basis,
                status="CLOSED",
                realized_gain_cents=realized,
                close_date=now,
                wash_window_start=(now - timedelta(days=WASH_WINDOW_DAYS)) if realized < 0 else None,
                wash_window_end=(now + timedelta(days=WASH_WINDOW_DAYS)) if realized < 0 else None,
            )
            account["next_order_sequence"] += 1
            db.tax_lots[slice_row["id"]] = slice_row
            lot["shares_open"] -= take
            lot["cost_basis_cents"] -= basis
            touch(lot)
            closed_rows.append(slice_row)
    return closed_rows


# ---------------------------------------------------------------------------
# wash_sale_window_geometry (scaffold 1.3 / PRD 2.10)
# ---------------------------------------------------------------------------
def wash_lookback_conflict(account_id, security_id):
    """Clause L - a TRADE-origin acquisition inside the closed +/-30 day window."""
    today = clock().date()
    low = today - timedelta(days=WASH_WINDOW_DAYS)
    high = today + timedelta(days=WASH_WINDOW_DAYS)
    for lot in db.tax_lots.values():
        if lot["account_id"] != account_id or lot["security_id"] != security_id:
            continue
        if lot["origin"] != "TRADE":
            continue
        if lot["status"] not in ("OPEN", "CLOSED"):
            continue
        open_date = lot.get("open_date")
        if open_date is None:
            continue
        if low <= open_date.date() <= high:
            return True
    return False


def wash_window_occupied(account_id, security_id):
    """Clause W - the clock date sits inside a losing lot's stamped window."""
    today = clock().date()
    for lot in db.tax_lots.values():
        if lot["account_id"] != account_id or lot["security_id"] != security_id:
            continue
        if lot["status"] != "CLOSED":
            continue
        realized = lot.get("realized_gain_cents")
        if realized is None or realized >= 0:
            continue
        start = lot.get("wash_window_start")
        end = lot.get("wash_window_end")
        if start is None or end is None:
            continue
        if start.date() <= today <= end.date():
            return True
    return False


# ---------------------------------------------------------------------------
# fee_invoice_tiered_split (scaffold 1.3 / PRD 3.9)
# ---------------------------------------------------------------------------
def compute_fee_invoice(model, sponsor, billing_days, adv):
    slice1 = min(adv, TIER1_CEILING_CENTS)
    slice2 = max(0, min(adv, TIER2_CEILING_CENTS) - TIER1_CEILING_CENTS)
    slice3 = max(0, adv - TIER2_CEILING_CENTS)

    bps1 = model["base_fee_bps"]
    bps2 = model["base_fee_bps"] - TIER2_DISCOUNT_BPS
    bps3 = model["base_fee_bps"] - TIER3_DISCOUNT_BPS

    denom = TOTAL_BPS * DAYS_IN_YEAR
    tier1 = round_half_up(slice1 * bps1 * billing_days, denom)
    tier2 = round_half_up(slice2 * bps2 * billing_days, denom)
    tier3 = round_half_up(slice3 * bps3 * billing_days, denom)
    gross = tier1 + tier2 + tier3

    sponsor_share = round_half_up(gross * sponsor["revenue_share_bps"], TOTAL_BPS)
    platform_share = round_half_up(gross * PLATFORM_FEE_BPS, TOTAL_BPS)
    manager_share = gross - sponsor_share - platform_share

    return {
        "tier1_fee_cents": tier1,
        "tier2_fee_cents": tier2,
        "tier3_fee_cents": tier3,
        "gross_fee_cents": gross,
        "sponsor_share_cents": sponsor_share,
        "platform_share_cents": platform_share,
        "manager_share_cents": manager_share,
    }


# ---------------------------------------------------------------------------
# Interval overlap helpers (scaffold 1.3 / PRD 2.10)
# ---------------------------------------------------------------------------
def half_open_collides(a_start, a_end, b_start, b_end):
    """Half-open [start, end); a null end means unbounded.  Adjacency is legal."""
    if a_end is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start >= b_end:
        return False
    return True


# ---------------------------------------------------------------------------
# cross_account_dispersion (scaffold 1.3 / PRD 3.6)
# ---------------------------------------------------------------------------
def dispersion_report(model_version_id, basis):
    cohort = [a for a in db.accounts.values()
              if a.get("current_model_version_id") == model_version_id
              and a["implementation_status"] != "SUSPENDED"
              and a.get("latest_return_bps") is not None]
    if not cohort:
        raise ApiError("ERR_DISPERSION_SET_EMPTY", "The dispersion cohort is empty.")

    n = len(cohort)
    returns = [a["latest_return_bps"] for a in cohort]
    min_return = min(returns)
    max_return = max(returns)

    if basis == "ASSET_WEIGHTED":
        weights = [(a["latest_ending_value_cents"] or 0) for a in cohort]
        weight_sum = sum(weights)
        if weight_sum == 0:
            mean = round_half_up(sum(returns), n)
            mad = round_half_up(sum(abs(r - mean) for r in returns), n)
        else:
            mean = round_half_up(sum(r * w for r, w in zip(returns, weights)), weight_sum)
            mad = round_half_up(sum(w * abs(r - mean) for r, w in zip(returns, weights)),
                                weight_sum)
    else:
        mean = round_half_up(sum(returns), n)
        mad = round_half_up(sum(abs(r - mean) for r in returns), n)

    return {
        "model_version_id": model_version_id,
        "basis": basis,
        "account_count": n,
        "mean_return_bps": mean,
        "mean_abs_deviation_bps": mad,
        "dispersion_bps": max_return - min_return,
        "min_return_bps": min_return,
        "max_return_bps": max_return,
    }
