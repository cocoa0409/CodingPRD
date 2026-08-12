"""Business logic services: recomputes, cascades, coverage cap, margin, tick cascade."""

import math
from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

import db
from db import DB
from errors import ApiError
from helpers import D, r2, r4, to_float, touch, latest_settlement_tick, parse_date


RISK_TREND_FACTOR = {
    "CONSERVATIVE": Decimal("0.98"),
    "BALANCED": Decimal("1.00"),
    "AGGRESSIVE": Decimal("1.02"),
}

RISK_COVERAGE_CAP = {
    "CONSERVATIVE": Decimal("0.60"),
    "BALANCED": Decimal("0.80"),
    "AGGRESSIVE": Decimal("1.00"),
}

IM_RATE_FUTURES_SHORT = Decimal("0.30")
MM_RATE_FUTURES_SHORT = Decimal("0.22")
LONG_PUT_IM_ADD = Decimal("0.05")

RECOMMENDATION_TTL_DAYS = 5

MOISTURE_BASE_PCT = Decimal("15.0")
SHRINK_PER_POINT = Decimal("0.012")
OVER_DELIVERY_TOLERANCE = Decimal("1.02")

COMMITTED_FULFILLMENT = {"OPEN", "PARTIALLY_DELIVERED", "DELIVERED"}


# ---------------------------------------------------------------------------
# Plan counters
# ---------------------------------------------------------------------------

def plan_contracts(plan_id):
    return [c for c in DB.contracts.values() if c["plan_id"] == plan_id]


def recompute_plan_counters(plan):
    """Recompute committed/uncommitted/hedged/priced/pending counters and touch plan."""
    pid = plan["id"]

    committed = 0
    priced = 0
    for c in DB.contracts.values():
        if c["plan_id"] != pid:
            continue
        fs = c["fulfillment_status"]
        if fs in COMMITTED_FULFILLMENT:
            if fs == "DEFAULTED":
                committed += max(0, c["bushels"] - int(c["delivered_bushels"]))
            else:
                committed += c["bushels"]
            if c["pricing_status"] == "PRICED" and fs in {"OPEN", "PARTIALLY_DELIVERED", "DELIVERED"}:
                priced += c["bushels"]
        elif fs == "DEFAULTED":
            # DEFAULTED releases undelivered balance: committed += delivered only
            committed += 0  # delivered part stays? per spec: releases its (undelivered) commitment
            # delivered portion is already settled; commitment released on undelivered only.
            # Simpler: committed counts only OPEN/PARTIALLY_DELIVERED/DELIVERED (scaffold).
            pass
    # Recompute per scaffold: committed = sum over OPEN, PARTIALLY_DELIVERED, DELIVERED
    committed = 0
    priced = 0
    for c in DB.contracts.values():
        if c["plan_id"] != pid:
            continue
        fs = c["fulfillment_status"]
        if fs in {"OPEN", "PARTIALLY_DELIVERED", "DELIVERED"}:
            committed += c["bushels"]
            if c["pricing_status"] == "PRICED":
                priced += c["bushels"]

    hedged = 0
    for p in DB.positions.values():
        if p["plan_id"] == pid and p["status"] == "OPEN":
            hedged += p["bushels"]
    for rec in DB.recommendations.values():
        if rec["plan_id"] == pid and rec["status"] == "ACCEPTED":
            hedged += rec["bushels"]

    pending = 0
    for rec in DB.recommendations.values():
        if rec["plan_id"] == pid and rec["status"] == "PROPOSED":
            pending += 1

    plan["committed_contract_bushels"] = committed
    plan["uncommitted_bushels"] = (plan.get("expected_bushels_snapshot") or 0) - committed
    plan["hedged_bushels"] = hedged
    plan["priced_contract_bushels"] = priced
    plan["pending_recommendation_count"] = pending
    touch(plan)


def compute_coverage_cap(plan, operation):
    """floor(snapshot * min(max_priced_pct, RISK_COVERAGE_CAP[risk_profile]))."""
    snapshot = plan.get("expected_bushels_snapshot")
    if snapshot is None:
        return 0
    op_cap = RISK_COVERAGE_CAP[operation["risk_profile"]]
    eff = min(D(plan["max_priced_pct"]), op_cap)
    return int((D(snapshot) * eff).to_integral_value(rounding="ROUND_FLOOR"))


# ---------------------------------------------------------------------------
# Margin accounting
# ---------------------------------------------------------------------------

def position_initial_margin(instrument, bushels, premium_per_bushel=None):
    if instrument == "FUTURES_SHORT":
        return r2(D(bushels) * IM_RATE_FUTURES_SHORT)
    else:  # LONG_PUT
        return r2(D(bushels) * (D(premium_per_bushel) + LONG_PUT_IM_ADD))


def position_maintenance_margin(instrument, bushels, premium_per_bushel=None):
    if instrument == "FUTURES_SHORT":
        return r2(D(bushels) * MM_RATE_FUTURES_SHORT)
    else:
        return position_initial_margin(instrument, bushels, premium_per_bushel)


def position_unrealized_pnl(pos, latest_settlement):
    """latest_settlement: Decimal price."""
    if pos["instrument"] == "FUTURES_SHORT":
        return r2((D(pos["entry_price"]) - latest_settlement) * pos["bushels"])
    else:
        intrinsic = max(Decimal("0"), D(pos["strike_price"]) - latest_settlement)
        return r2((intrinsic - D(pos["premium_per_bushel"])) * pos["bushels"])


def position_realized_pnl(pos, exit_price):
    if pos["instrument"] == "FUTURES_SHORT":
        return r2((D(pos["entry_price"]) - exit_price) * pos["bushels"])
    else:
        intrinsic = max(Decimal("0"), D(pos["strike_price"]) - exit_price)
        return r2((intrinsic - D(pos["premium_per_bushel"])) * pos["bushels"])


def account_open_positions(account_id):
    return [p for p in DB.positions.values() if p["margin_account_id"] == account_id and p["status"] == "OPEN"]


def recompute_margin_account(account):
    """Recompute margin aggregates from current state and touch."""
    positions = account_open_positions(account["id"])
    im = sum(D(p["initial_margin_dollars"]) for p in positions)
    mm = sum(D(p["maintenance_margin_dollars"]) for p in positions)
    unreal = sum(D(p["unrealized_pnl"]) for p in positions)
    account["initial_margin_required"] = to_float(r2(im))
    account["maintenance_margin_required"] = to_float(r2(mm))
    account["margin_equity"] = to_float(r2(D(account["cash_balance"]) + unreal))
    if account["status"] != "CALL_OUTSTANDING":
        account["margin_call_amount"] = 0.0
    touch(account)


# ---------------------------------------------------------------------------
# Governing agreement
# ---------------------------------------------------------------------------

def governing_agreement(operation_id):
    """Most recently activated ACTIVE agreement; tie-break greatest created_at."""
    actives = [
        a for a in DB.agreements.values()
        if a["operation_id"] == operation_id and a["status"] == "ACTIVE"
    ]
    if not actives:
        return None
    actives.sort(key=lambda a: a["created_at"], reverse=True)
    return actives[0]


# ---------------------------------------------------------------------------
# Over-sold flag evaluation
# ---------------------------------------------------------------------------

def evaluate_over_sold(operation_id, actual_harvested_bushels=None):
    """Set/clear operation.over_sold_flag.
    Marketable bushels: after a settled claim, actual_harvested_bushels of the most recent
    CLAIM_SETTLED policy; otherwise (no claim) no tripwire applies."""
    op = DB.operations[operation_id]
    # Find latest CLAIM_SETTLED policy for the operation
    settled = [
        p for p in DB.policies.values()
        if p["operation_id"] == operation_id and p["status"] == "CLAIM_SETTLED"
    ]
    if not settled:
        # No settled claim: flag unchanged (remains whatever it was; default false)
        return
    settled.sort(key=lambda p: p["created_at"], reverse=True)
    marketable = settled[0].get("actual_harvested_bushels") or 0
    undelivered = 0
    for c in DB.contracts.values():
        if c["operation_id"] != operation_id:
            continue
        if c["fulfillment_status"] in {"OPEN", "PARTIALLY_DELIVERED"}:
            undelivered += max(0, c["bushels"] - int(c["delivered_bushels"]))
    new_flag = undelivered > marketable
    if op["over_sold_flag"] != new_flag:
        op["over_sold_flag"] = new_flag
        touch(op)


# ---------------------------------------------------------------------------
# Tick cascade
# ---------------------------------------------------------------------------

def process_tick_cascade(tick):
    """Three-hop cascade: targets -> expiry -> margin re-marking."""
    # Hop 1: fire eligible PENDING price targets (QUOTE and SETTLEMENT both fire)
    fire_price_targets(tick)
    # Hop 2: expire PROPOSED recommendations older than 5 days
    expire_stale_recommendations()
    # Hop 3: SETTLEMENT ticks re-mark OPEN positions of matching commodity+month
    if tick["kind"] == "SETTLEMENT":
        remark_positions(tick)


def fire_price_targets(tick):
    """Eligible PENDING targets fire in target_price ASC, created_at ASC order."""
    eligible = []
    for t in DB.price_targets.values():
        if t["status"] != "PENDING":
            continue
        plan = DB.plans.get(t["plan_id"])
        if plan is None or plan["status"] != "ACTIVE":
            continue
        op = DB.operations.get(plan["operation_id"])
        if op is None:
            continue
        if op["primary_commodity"] != tick["commodity"]:
            continue
        if t["contract_month"] != tick["contract_month"]:
            continue
        if D(tick["price"]) < D(t["target_price"]):
            continue
        eligible.append(t)

    eligible.sort(key=lambda t: (D(t["target_price"]), t["created_at"]))

    for target in eligible:
        plan = DB.plans[target["plan_id"]]
        # pending headroom = cap - hedged - priced - sum(PROPOSED bushels)
        cap = plan["coverage_cap_bushels"]
        proposed_sum = sum(
            r["bushels"]
            for r in DB.recommendations.values()
            if r["plan_id"] == plan["id"] and r["status"] == "PROPOSED"
        )
        headroom = cap - plan["hedged_bushels"] - plan["priced_contract_bushels"] - proposed_sum
        if headroom <= 0:
            target["status"] = "LAPSED"
            touch(target)
            continue
        bushels = min(target["increment_bushels"], headroom)
        bushels = max(0, bushels)
        # Mint recommendation
        rec_id = db.new_id()
        now = db.now_iso()
        rec = {
            "id": rec_id,
            "plan_id": plan["id"],
            "price_target_id": target["id"],
            "instrument": "FUTURES_SHORT",
            "contract_month": target["contract_month"],
            "bushels": bushels,
            "strike_price": None,
            "premium_per_bushel": None,
            "rationale": None,
            "created_by_user_id": None,
            "status": "PROPOSED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        DB.recommendations[rec_id] = rec
        target["status"] = "TRIGGERED"
        target["recommendation_id"] = rec_id
        touch(target)
        recompute_plan_counters(plan)


def expire_stale_recommendations():
    """PROPOSED recs whose created_at is more than 5 days before current logical clock."""
    now = db.logical_now()
    for rec in list(DB.recommendations.values()):
        if rec["status"] != "PROPOSED":
            continue
        created = _parse_entity_ts(rec["created_at"])
        if (now - created).total_seconds() > RECOMMENDATION_TTL_DAYS * 86400:
            rec["status"] = "EXPIRED"
            touch(rec)
            plan = DB.plans.get(rec["plan_id"])
            if plan:
                recompute_plan_counters(plan)
            pt_id = rec.get("price_target_id")
            if pt_id and pt_id in DB.price_targets:
                pt = DB.price_targets[pt_id]
                if pt["status"] == "TRIGGERED":
                    pt["status"] = "LAPSED"
                    touch(pt)


def _parse_entity_ts(ts):
    txt = ts
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    from datetime import timezone as tz

    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz.utc)
    return dt


def remark_positions(tick):
    """SETTLEMENT tick re-marks every OPEN position matching commodity+contract_month."""
    for pos in DB.positions.values():
        if pos["status"] != "OPEN":
            continue
        op = DB.operations.get(pos["operation_id"])
        if op is None or op["primary_commodity"] != tick["commodity"]:
            continue
        if pos["contract_month"] != tick["contract_month"]:
            continue
        pos["unrealized_pnl"] = to_float(position_unrealized_pnl(pos, D(tick["price"])))
        touch(pos)
        account = DB.margin_accounts.get(pos["margin_account_id"])
        if account:
            recompute_margin_account(account)
            # Call issuance: equity strictly below maintenance
            if (
                account["status"] == "FUNDED"
                and D(account["margin_equity"]) < D(account["maintenance_margin_required"])
            ):
                account["status"] = "CALL_OUTSTANDING"
                account["margin_call_amount"] = to_float(
                    r2(D(account["initial_margin_required"]) - D(account["margin_equity"]))
                )
                touch(account)
