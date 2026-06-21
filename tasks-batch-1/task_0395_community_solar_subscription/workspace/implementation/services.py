"""Business logic: ledger recomputation, allocation waterfall, calculations,
churn risk, and serialization. PRD §2.5-§2.7, §3.

All monetary calculations use Decimal with ROUND_HALF_UP where a non-integer
intermediate must land on an integer; floors/ceilings are applied where the PRD
explicitly calls for them.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

from db import store

# --- Calculation constants (SCAFFOLD §1.3) ---------------------------------
CARVE_OUT_FEE_RATE = Decimal("0.05")
TIER1_CENTS = 5000
TIER2_CENTS = 20000
ROLLOVER_CAP_KWH = 2000
CAP_KWH_PER_KW = 50
KWH_PER_REC = 1000

# churn risk weights
W_SUSPENDED = 40
W_OPEN_DISPUTE = 35
W_LOW_INCOME = 10
W_RECENT_CANCEL = 50

ACTIVE_SET = {"ACTIVE", "SUSPENDED", "TRANSFERRING"}


def round_half_up(value):
    """Round a Decimal/number to the nearest whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round3(value):
    """Round to three decimal places, half up. Returns a float."""
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# ===========================================================================
# Project ledger recomputation (PRD §2.5)
# ===========================================================================
def project_subscriptions(project_id):
    return [s for s in store.subscriptions.values() if s["project_id"] == project_id]


def recompute_project_ledger(project):
    """Recompute committed/available/carve-out derived fields and status."""
    pid = project["id"]
    subs = project_subscriptions(pid)
    committed = sum(
        s["share_kw"] for s in subs if s["status"] in ACTIVE_SET
    )
    carve_committed = sum(
        s["share_kw"]
        for s in subs
        if s["status"] in ACTIVE_SET and s["is_carve_out"]
    )
    nameplate = project["nameplate_capacity_kw"]
    available = nameplate - committed
    if available < 0:
        available = 0
    carve_reserved = round3(nameplate * project["carve_out_pct"])
    carve_available = carve_reserved - carve_committed
    if carve_available < 0:
        carve_available = 0
    project["committed_kw"] = committed
    project["carve_out_committed_kw"] = carve_committed
    project["available_kw"] = available
    project["carve_out_available_kw"] = carve_available
    project["status"] = "FULL" if available == 0 else "OPEN"


def recompute_project_rec_totals(project):
    pid = project["id"]
    batches = [b for b in store.rec_batches.values() if b["project_id"] == pid]
    minted = 0
    for b in batches:
        period = store.periods.get(b["period_id"])
        if period and period["status"] in ("RECONCILED", "TRUED_UP", "CLOSED"):
            minted += b["rec_count"]
    retired = sum(b["rec_count"] for b in batches if b["status"] == "RETIRED")
    transferred = sum(b["rec_count"] for b in batches if b["status"] == "TRANSFERRED")
    project["rec_minted_total"] = minted
    project["rec_retired_total"] = retired
    project["rec_available_balance"] = minted - retired - transferred


def recompute_project_net_savings(project):
    pid = project["id"]
    total = 0
    for r in store.reconciliations.values():
        if r.get("credit_status") != "APPLIED":
            continue
        period = store.periods.get(r["period_id"])
        if period and period["project_id"] == pid:
            total += r["net_savings_cents"]
    project["total_net_savings_cents"] = total


# ===========================================================================
# Subscriber derived fields (PRD §3.2)
# ===========================================================================
def recompute_lifetime_savings(subscriber):
    sid = subscriber["id"]
    total = 0
    for r in store.reconciliations.values():
        if r.get("credit_status") != "APPLIED":
            continue
        if r["subscription_id"] is None:
            continue
        sub = store.subscriptions.get(r["subscription_id"])
        if sub and sub["subscriber_id"] == sid:
            total += r["net_savings_cents"]
    subscriber["lifetime_savings_cents"] = total


def recompute_churn_risk(subscriber):
    """Snapshot/trailing weighted churn score (PRD §3.2)."""
    sid = subscriber["id"]
    base = 0
    subs = [s for s in store.subscriptions.values() if s["subscriber_id"] == sid]
    if any(s["status"] == "SUSPENDED" for s in subs):
        base += W_SUSPENDED
    # any reconciliation of this subscriber currently DISPUTED
    has_dispute = False
    for r in store.reconciliations.values():
        if r.get("dispute_status") != "DISPUTED":
            continue
        sub = store.subscriptions.get(r["subscription_id"])
        if sub and sub["subscriber_id"] == sid:
            has_dispute = True
            break
    if has_dispute:
        base += W_OPEN_DISPUTE
    if subscriber["is_low_income"]:
        base += W_LOW_INCOME
    # trailing variant: a subscription cancelled within the last 3 CLOSED periods.
    if _has_recent_cancel(sid):
        base += W_RECENT_CANCEL
    subscriber["churn_risk_score"] = min(100, base)


def _has_recent_cancel(subscriber_id):
    """True when this subscriber has a CANCELLED subscription whose
    cancellation_effective_period_id is among the last three CLOSED periods
    (by sequence_index, per project)."""
    cancelled = [
        s for s in store.subscriptions.values()
        if s["subscriber_id"] == subscriber_id and s["status"] == "CANCELLED"
    ]
    if not cancelled:
        return False
    for s in cancelled:
        period_id = s.get("cancellation_effective_period_id")
        if not period_id:
            continue
        period = store.periods.get(period_id)
        if not period or period["status"] != "CLOSED":
            continue
        pid = period["project_id"]
        closed = sorted(
            [p for p in store.periods.values()
             if p["project_id"] == pid and p["status"] == "CLOSED"],
            key=lambda p: p["sequence_index"],
        )
        last_three = closed[-3:]
        if period["id"] in {p["id"] for p in last_three}:
            return True
    return False


# ===========================================================================
# Billing period derived fields (PRD §3.7)
# ===========================================================================
def period_distributable(period):
    if period["status"] in ("METERED", "RECONCILED", "TRUED_UP", "CLOSED"):
        return period["metered_production_kwh"] or 0
    return period["forecast_production_kwh"]


def period_allocations(period_id):
    return [a for a in store.allocations.values() if a["period_id"] == period_id]


def recompute_period_derived(period):
    allocs = period_allocations(period["id"])
    allocated_total = sum(
        a["allocated_kwh"] for a in allocs if a["status"] in ("PROVISIONAL", "FINAL")
    )
    distributable = period_distributable(period)
    period["distributable_kwh"] = distributable
    period["allocated_kwh_total"] = allocated_total
    period["overproduction_kwh"] = distributable - allocated_total


def eligible_subscriptions_for_period(period):
    """A subscription is eligible if status == ACTIVE and either it has no
    cancellation_effective_period_id, or the period it names has a
    sequence_index strictly greater than this period's sequence_index.
    SUSPENDED subscriptions are excluded."""
    result = []
    for s in store.subscriptions.values():
        if s["project_id"] != period["project_id"]:
            continue
        if s["status"] != "ACTIVE":
            continue
        cep = s.get("cancellation_effective_period_id")
        if cep:
            cancel_period = store.periods.get(cep)
            if cancel_period and cancel_period["sequence_index"] <= period["sequence_index"]:
                continue
        result.append(s)
    return result


def run_waterfall(period):
    """Allocation waterfall (PRD §3.7). Sets allocated_kwh on each allocation
    of this period, matched to eligible subscriptions. Returns nothing; mutates
    allocations in place. Allocations for ineligible subscriptions get 0."""
    pool = period_distributable(period)
    eligible = eligible_subscriptions_for_period(period)
    allocs_by_sub = {a["subscription_id"]: a for a in period_allocations(period["id"])}

    total_share = sum(s["share_kw"] for s in eligible)
    # Reset all allocations of this period to 0 first.
    for a in allocs_by_sub.values():
        a["allocated_kwh"] = 0

    if total_share == 0 or pool == 0:
        for a in allocs_by_sub.values():
            a["allocated_kwh"] = 0
        return

    raws = {}
    floors = {}
    for s in eligible:
        raw = Decimal(pool) * (Decimal(str(s["share_kw"])) / Decimal(str(total_share)))
        raws[s["id"]] = raw
        floors[s["id"]] = int(math.floor(raw))

    remainder = pool - sum(floors.values())

    # distribute leftover by descending fractional part, tie-break created_at asc
    def frac(s):
        return raws[s["id"]] - Decimal(floors[s["id"]])

    order = sorted(
        eligible,
        key=lambda s: (-frac(s), s["created_at"], s["_seq"]),
    )
    extra = {s["id"]: 0 for s in eligible}
    # remainder is strictly less than len(eligible) (it is pool - sum(floors)),
    # so a single pass handing out one kWh each is sufficient; each subscription
    # receives at most one extra kWh (PRD §3.7).
    for s in order:
        if remainder <= 0:
            break
        extra[s["id"]] += 1
        remainder -= 1

    for s in eligible:
        alloc = allocs_by_sub.get(s["id"])
        if alloc is not None:
            alloc["allocated_kwh"] = floors[s["id"]] + extra[s["id"]]


# ===========================================================================
# Bill credit (PRD §3.8) and tiered program fee (PRD §3.10)
# ===========================================================================
def provisional_credit(allocated_kwh, project):
    return allocated_kwh * project["credit_rate_cents_per_kwh"]


def final_credit(allocated_kwh, project):
    return allocated_kwh * project["credit_rate_cents_per_kwh"]


def tiered_program_fee(gross, subscription, project):
    """program_fee_cents = round_half_up(gross * base_rate * tier_multiplier)."""
    if subscription["is_carve_out"]:
        base_rate = CARVE_OUT_FEE_RATE
    else:
        base_rate = Decimal(str(project["program_fee_rate"]))
    if gross <= TIER1_CENTS:
        m = Decimal("1.00")
    elif gross <= TIER2_CENTS:
        m = Decimal("0.90")
    else:
        m = Decimal("0.80")
    fee = round_half_up(Decimal(gross) * base_rate * m)
    return fee


# ===========================================================================
# True-up overproduction sweep (PRD §3.12)
# ===========================================================================
def trueup_sweep(period, project):
    recompute_period_derived(period)
    overproduction = period["overproduction_kwh"]
    cap = min(
        ROLLOVER_CAP_KWH,
        int(math.ceil(project["committed_kw"] * CAP_KWH_PER_KW)),
    )
    rollover = min(overproduction, cap)
    if rollover < 0:
        rollover = 0
    forfeited = overproduction - rollover
    rollover_credit = rollover * project["credit_rate_cents_per_kwh"]
    period["rollover_kwh"] = rollover
    period["forfeited_kwh"] = forfeited
    period["rollover_credit_cents"] = rollover_credit


# ===========================================================================
# REC minting (PRD §3.10)
# ===========================================================================
def rec_count_for_period(period):
    return int(math.floor((period["metered_production_kwh"] or 0) / KWH_PER_REC))


# ===========================================================================
# Serializers — only PRD-declared fields, in entity order.
# ===========================================================================
def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def serialize_project(p):
    recompute_project_ledger(p)
    recompute_project_rec_totals(p)
    recompute_project_net_savings(p)
    out = {
        "name": p["name"],
        "state_code": p["state_code"],
        "nameplate_capacity_kw": p["nameplate_capacity_kw"],
        "carve_out_pct": p["carve_out_pct"],
        "credit_rate_cents_per_kwh": p["credit_rate_cents_per_kwh"],
        "program_fee_rate": p["program_fee_rate"],
        "committed_kw": p["committed_kw"],
        "carve_out_committed_kw": p["carve_out_committed_kw"],
        "available_kw": p["available_kw"],
        "carve_out_available_kw": p["carve_out_available_kw"],
        "rec_minted_total": p["rec_minted_total"],
        "rec_retired_total": p["rec_retired_total"],
        "rec_available_balance": p["rec_available_balance"],
        "total_net_savings_cents": p["total_net_savings_cents"],
        "status": p["status"],
    }
    out.update(_common(p))
    return out


def serialize_subscriber(s):
    recompute_churn_risk(s)
    recompute_lifetime_savings(s)
    out = {
        "full_name": s["full_name"],
        "utility_account_no": s["utility_account_no"],
        "state_code": s["state_code"],
        "is_low_income": s["is_low_income"],
        "annual_usage_kwh": s["annual_usage_kwh"],
        "churn_risk_score": s["churn_risk_score"],
        "lifetime_savings_cents": s["lifetime_savings_cents"],
    }
    out.update(_common(s))
    return out


def serialize_enrollment(e):
    out = {
        "project_id": e["project_id"],
        "subscriber_id": e["subscriber_id"],
        "requested_share_kw": e["requested_share_kw"],
        "status": e["status"],
        "rejection_reason": e.get("rejection_reason"),
        "subscription_id": e.get("subscription_id"),
    }
    out.update(_common(e))
    return out


def serialize_subscription(s):
    out = {
        "project_id": s["project_id"],
        "subscriber_id": s["subscriber_id"],
        "enrollment_id": s["enrollment_id"],
        "share_kw": s["share_kw"],
        "is_carve_out": s["is_carve_out"],
        "status": s["status"],
        "transferred_from_subscription_id": s.get("transferred_from_subscription_id"),
        "cancellation_effective_period_id": s.get("cancellation_effective_period_id"),
    }
    out.update(_common(s))
    return out


def serialize_waitlist(w):
    out = {
        "project_id": w["project_id"],
        "subscriber_id": w["subscriber_id"],
        "requested_share_kw": w["requested_share_kw"],
        "queued_at": w["queued_at"],
        "status": w["status"],
        "promoted_enrollment_id": w.get("promoted_enrollment_id"),
    }
    out.update(_common(w))
    return out


def serialize_period(p):
    recompute_period_derived(p)
    out = {
        "project_id": p["project_id"],
        "period_month": p["period_month"],
        "sequence_index": p["sequence_index"],
        "forecast_production_kwh": p["forecast_production_kwh"],
        "metered_production_kwh": p.get("metered_production_kwh"),
        "status": p["status"],
        "distributable_kwh": p["distributable_kwh"],
        "allocated_kwh_total": p["allocated_kwh_total"],
        "overproduction_kwh": p["overproduction_kwh"],
        "rollover_kwh": p.get("rollover_kwh", 0),
        "forfeited_kwh": p.get("forfeited_kwh", 0),
        "rollover_credit_cents": p.get("rollover_credit_cents", 0),
        "rec_minted_count": p.get("rec_minted_count", 0),
    }
    out.update(_common(p))
    return out


def serialize_allocation(a):
    out = {
        "period_id": a["period_id"],
        "subscription_id": a["subscription_id"],
        "share_kw_snapshot": a["share_kw_snapshot"],
        "allocated_kwh": a["allocated_kwh"],
        "provisional_credit_cents": a["provisional_credit_cents"],
        "final_credit_cents": a.get("final_credit_cents"),
        "status": a["status"],
    }
    out.update(_common(a))
    return out


def serialize_reconciliation(r):
    out = {
        "subscription_id": r["subscription_id"],
        "period_id": r["period_id"],
        "allocation_id": r["allocation_id"],
        "gross_credit_cents": r["gross_credit_cents"],
        "program_fee_cents": r["program_fee_cents"],
        "net_savings_cents": r["net_savings_cents"],
        "credit_status": r["credit_status"],
        "dispute_status": r["dispute_status"],
    }
    out.update(_common(r))
    return out


def serialize_rec_batch(b):
    out = {
        "project_id": b["project_id"],
        "period_id": b["period_id"],
        "rec_count": b["rec_count"],
        "retirement_beneficiary": b.get("retirement_beneficiary"),
        "transfer_counterparty": b.get("transfer_counterparty"),
        "status": b["status"],
    }
    out.update(_common(b))
    return out


def serialize_carve_out_adjustment(c):
    # Append-only: only id and created_at common fields (PRD §2.4).
    return {
        "project_id": c["project_id"],
        "previous_carve_out_pct": c["previous_carve_out_pct"],
        "new_carve_out_pct": c["new_carve_out_pct"],
        "reason": c["reason"],
        "id": c["id"],
        "created_at": c["created_at"],
    }
