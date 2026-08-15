"""Calculation rules (SCAFFOLD Table 3 / PRD §3).

Money is integer cents throughout; rounding uses Decimal ROUND_HALF_UP.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, parse_iso, fmt_iso, clock_now
from services.entities import touch


# ---------------------------------------------------------------------------
# alert_score
# ---------------------------------------------------------------------------

WEIGHTS = {
    "REFUND_NO_RECEIPT": 10,
    "HIGH_VALUE_VOID": 14,
    "PRICE_OVERRIDE": 8,
    "NO_SALE_DRAWER": 6,
    "SUSPEND_CANCEL": 8,
    "SWEETHEART_SCAN": 12,
    "SELF_CHECKOUT_MISMATCH": 9,
}

OPEN_THRESHOLD = Decimal("40.00")
ESCALATE_THRESHOLD = Decimal("75.00")
WINDOW_DAYS = 30


def band_mult(amount_cents):
    if amount_cents < 5000:
        return Decimal("1.0")
    if amount_cents < 20000:
        return Decimal("1.5")
    return Decimal("2.0")


def score_events(events):
    """Weighted sum rounded half-up to 2 decimal places; returned as Decimal."""
    total = Decimal("0")
    for e in events:
        total += Decimal(WEIGHTS[e["exception_type"]]) * band_mult(e["amount_cents"])
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# civil_demand_amount
# ---------------------------------------------------------------------------

def tier_penalty(loss_cents):
    """Tiered statutory penalty on the snapshotted merchandise loss (integral)."""
    loss = Decimal(loss_cents)
    if loss <= 50000:
        return 10000
    if loss <= 150000:
        extra = (Decimal("0.10") * (loss - 50000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        return 25000 + int(extra)
    extra = (Decimal("0.20") * (loss - 150000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return min(100000, 50000 + int(extra))


def statutory_penalty(loss_cents, priors):
    """Tier penalty multiplied by the prior-offense multiplier, rounded after."""
    tier = tier_penalty(loss_cents)
    counted = min(priors, 4)
    mult = Decimal("1.0") + Decimal("0.5") * counted
    if mult > Decimal("3.0"):
        mult = Decimal("3.0")
    penalty = (Decimal(tier) * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(penalty)


def compute_demand_amounts(basis, merch_loss_cents, priors, recovery_cost_cents):
    """Returns (statutory_penalty_cents, amount_due_cents)."""
    if basis == "ACTUAL_LOSS":
        penalty = 0
    else:
        penalty = statutory_penalty(merch_loss_cents, priors)
    amount_due = merch_loss_cents + penalty + recovery_cost_cents
    return penalty, amount_due


# ---------------------------------------------------------------------------
# restitution_waterfall
# ---------------------------------------------------------------------------

NSF_FEE_CENTS = 2500


def waterfall_allocate(demand, amount_cents):
    """Allocate a posting across fees -> penalty -> merch buckets."""
    remaining = amount_cents
    fees_unpaid = demand["fees_incurred_cents"] - demand["_fees_paid_cents"]
    applied_fees = min(remaining, fees_unpaid)
    remaining -= applied_fees
    penalty_unpaid = demand["statutory_penalty_cents"] - demand["_penalty_paid_cents"]
    applied_penalty = min(remaining, penalty_unpaid)
    remaining -= applied_penalty
    merch_unpaid = (demand["merchandise_loss_cents"] + demand["recovery_cost_cents"]
                    - demand["_merch_paid_cents"])
    applied_merch = min(remaining, merch_unpaid)
    remaining -= applied_merch
    return applied_fees, applied_penalty, applied_merch


def demand_outstanding(demand):
    return (demand["amount_due_cents"] + demand["fees_incurred_cents"]
            - demand["paid_to_date_cents"])


# ---------------------------------------------------------------------------
# case_total_loss
# ---------------------------------------------------------------------------

def case_event_sum(case_id):
    """Sum of amount_cents over events AGGREGATED to alerts with case_id = this."""
    total = 0
    for alert in db.alerts.values():
        if alert.get("case_id") == case_id:
            for eid in alert["_member_event_ids"]:
                ev = db.exception_events[eid]
                if ev["status"] == "AGGREGATED":
                    total += ev["amount_cents"]
    return total


def recompute_case_total_loss(case):
    raw = (case_event_sum(case["id"])
           + case["manual_loss_cents"]
           - case["recovered_value_cents"])
    case["total_loss_cents"] = max(0, raw)
    return case["total_loss_cents"]


# ---------------------------------------------------------------------------
# orc_escalation
# ---------------------------------------------------------------------------

MIN_CONFIRMED_CASES = 3
MIN_DISTINCT_STORES = 2
MIN_EXPOSURE_CENTS = 500000


def recompute_group_counters(group):
    """Recompute counters over CONFIRMED links; MERGED cases contribute only
    via their surviving target (a MERGED source case is excluded; the target
    counts if it is itself confirmed-linked)."""
    confirmed = [l for l in db.case_links.values()
                 if l["orc_group_id"] == group["id"] and l["status"] == "CONFIRMED"]
    case_ids = []
    for link in confirmed:
        case = db.cases.get(link["case_id"])
        if case is None:
            continue
        if case["status"] == "MERGED":
            continue  # contributes via surviving target only
        case_ids.append(case["id"])
    store_ids = set()
    exposure = 0
    for cid in case_ids:
        case = db.cases[cid]
        store_ids.add(case["store_id"])
        exposure += case["total_loss_cents"]
    group["confirmed_case_count"] = len(case_ids)
    group["distinct_store_count"] = len(store_ids)
    group["exposure_cents"] = exposure
    return group


def evaluate_group_escalation(group):
    """Flip IDENTIFIED <-> ACTIVE_MONITORING per conjunctive threshold and
    recompute priorities of confirmed-linked cases."""
    meets = (group["confirmed_case_count"] >= MIN_CONFIRMED_CASES
             and group["distinct_store_count"] >= MIN_DISTINCT_STORES
             and group["exposure_cents"] >= MIN_EXPOSURE_CENTS)
    changed = False
    if group["status"] == "IDENTIFIED" and meets:
        group["status"] = "ACTIVE_MONITORING"
        changed = True
    elif group["status"] == "ACTIVE_MONITORING" and not meets:
        group["status"] = "IDENTIFIED"
        changed = True
    if changed:
        touch(group)
        for link in db.case_links.values():
            if link["orc_group_id"] == group["id"] and link["status"] == "CONFIRMED":
                case = db.cases.get(link["case_id"])
                if case is not None and case["status"] != "MERGED":
                    recompute_case_priority(case)
    return changed


def recompute_case_priority(case):
    """HIGH when any source alert ESCALATED or any CONFIRMED link points at an
    ACTIVE_MONITORING group; STANDARD otherwise."""
    high = False
    for alert in db.alerts.values():
        if alert.get("case_id") == case["id"] and alert["status"] == "ESCALATED":
            high = True
            break
    if not high:
        for link in db.case_links.values():
            if link["case_id"] == case["id"] and link["status"] == "CONFIRMED":
                grp = db.orc_groups.get(link["orc_group_id"])
                if grp is not None and grp["status"] == "ACTIVE_MONITORING":
                    high = True
                    break
    new_priority = "HIGH" if high else "STANDARD"
    if case["priority"] != new_priority:
        case["priority"] = new_priority
        touch(case)


# ---------------------------------------------------------------------------
# shrink_accrual / shrink_variance
# ---------------------------------------------------------------------------

SALES_ACCRUAL_RATE = Decimal("0.0125")
VARIANCE_BREACH_PCT = Decimal("0.0200")


def recompute_period_accruals(period):
    period["accrual_case_basis_cents"] = period["known_loss_posted_cents"]
    period["accrual_sales_basis_cents"] = int(
        (Decimal(period["period_sales_cents"]) * SALES_ACCRUAL_RATE).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))


def compute_variance(period):
    variance_cents = (period["counted_inventory_cents"]
                      - (period["book_inventory_cents"]
                         - period["known_loss_posted_cents"]))
    pct = (Decimal(variance_cents) / Decimal(period["book_inventory_cents"]))
    variance_pct = pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return variance_cents, variance_pct


# ---------------------------------------------------------------------------
# evidence_retention
# ---------------------------------------------------------------------------

STANDARD_DAYS = 90
EXTENDED_DAYS = 365
CASE_HOLD_DAYS_AFTER_CLOSE = 30


def retention_until_for(retention_class, captured_at, case):
    """retention_until per class; CASE_HOLD resolves only while case closed."""
    cap = parse_iso(captured_at)
    if retention_class == "STANDARD":
        return fmt_iso(cap + timedelta(days=STANDARD_DAYS))
    if retention_class == "EXTENDED":
        return fmt_iso(cap + timedelta(days=EXTENDED_DAYS))
    # CASE_HOLD: case.closed_at + 30d while closed; not eligible while open.
    closed_at = case.get("closed_at")
    if closed_at:
        return fmt_iso(parse_iso(closed_at) + timedelta(days=CASE_HOLD_DAYS_AFTER_CLOSE))
    return None


def refresh_case_hold_retention(case):
    """Recompute CASE_HOLD items' retention_until when the case closes/reopens."""
    for item in db.evidence_items.values():
        if item["case_id"] == case["id"] and item["retention_class"] == "CASE_HOLD":
            new_until = retention_until_for("CASE_HOLD", item["captured_at"], case)
            if item["retention_until"] != new_until:
                item["retention_until"] = new_until
                touch(item)


# ---------------------------------------------------------------------------
# interview_doc_sla
# ---------------------------------------------------------------------------

DOC_SLA_HOURS = 72


def compute_doc_stale(conducted_at_iso, documented_at_iso):
    delta = parse_iso(documented_at_iso) - parse_iso(conducted_at_iso)
    return delta.total_seconds() > DOC_SLA_HOURS * 3600


# ---------------------------------------------------------------------------
# restitution_status rollup
# ---------------------------------------------------------------------------

def recompute_case_restitution_status(case, waived_hint=None):
    """NONE when no issued demand exists or restitution waived; else
    OUTSTANDING while collectible balance remains, SETTLED once none does."""
    demands = [d for d in db.civil_demands.values() if d["case_id"] == case["id"]]
    issued_like = [d for d in demands if d["status"] in
                   ("ISSUED", "PARTIALLY_PAID", "PAID_IN_FULL")]
    if not issued_like:
        case["restitution_status"] = "NONE"
        return case["restitution_status"]
    outstanding = any(d["outstanding_cents"] > 0 for d in issued_like)
    case["restitution_status"] = "OUTSTANDING" if outstanding else "SETTLED"
    return case["restitution_status"]
