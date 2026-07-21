"""Lookups, ledger mechanics, calculations and cascades."""
from decimal import Decimal

from core import (
    CHARGEBACK_WEIGHT,
    DEFAULT_SHARE_BPS,
    POLICY_STRIKE_SUSPEND_THRESHOLD,
    REFUND_WEIGHT,
    RISK_WINDOW_DAYS,
    STRIKE_WEIGHT,
    clock_now,
    db,
    days,
    fail,
    new_record,
    ordered,
    parse_iso,
    rhu,
    touch,
)

# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
_NOT_FOUND = {
    "developers": "ERR_DEVELOPER_NOT_FOUND",
    "apps": "ERR_APP_NOT_FOUND",
    "review_submissions": "ERR_REVIEW_SUBMISSION_NOT_FOUND",
    "pricing_plans": "ERR_PRICING_PLAN_NOT_FOUND",
    "tax_jurisdictions": "ERR_TAX_JURISDICTION_NOT_FOUND",
    "revenue_share_tiers": "ERR_REVENUE_SHARE_TIER_NOT_FOUND",
    "purchases": "ERR_PURCHASE_NOT_FOUND",
    "refunds": "ERR_REFUND_NOT_FOUND",
    "chargebacks": "ERR_CHARGEBACK_NOT_FOUND",
    "policy_cases": "ERR_POLICY_CASE_NOT_FOUND",
    "payout_batches": "ERR_PAYOUT_BATCH_NOT_FOUND",
    "payout_lines": "ERR_PAYOUT_LINE_NOT_FOUND",
    "ledger_entries": "ERR_LEDGER_ENTRY_NOT_FOUND",
    "tax_forms": "ERR_TAX_FORM_NOT_FOUND",
}


def lookup(collection, resource_id):
    rec = getattr(db, collection).get(resource_id)
    if rec is None:
        fail(_NOT_FOUND[collection], "%s not found." % collection[:-1])
    return rec


def jurisdiction_for(country_code):
    for row in ordered(db.tax_jurisdictions):
        if row["country_code"] == country_code:
            return row
    return None


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------
def write_entry(developer_id, entry_type, amount_cents, memo, purchase_id=None,
                payout_line_id=None, settled=False):
    entry = new_record(
        versioned=False,
        developer_id=developer_id,
        purchase_id=purchase_id,
        payout_line_id=payout_line_id,
        entry_type=entry_type,
        amount_cents=amount_cents,
        settled=settled,
        memo=memo,
    )
    db.ledger_entries[entry["id"]] = entry
    return entry


def developer_entries(developer_id):
    return [e for e in ordered(db.ledger_entries) if e["developer_id"] == developer_id]


def unsettled_sum(developer_id):
    return sum(e["amount_cents"] for e in developer_entries(developer_id) if not e["settled"])


def recompute_accrual(dev, recompute_negative_balance=False):
    """PRD §2.9: `unpaid_accrual_cents` is recomputed after every ledger movement as the
    sum over unsettled entries; `negative_balance_cents` "is populated whenever that
    recomputed sum comes out below zero, in which case the accrual figure is clamped to 0
    and the magnitude of the shortfall is carried in the negative balance instead."

    A positive sum therefore does not by itself erase a debt already carried: what the
    developer owes the marketplace is only discharged by the recovery step of the payout
    waterfall (§3.9/§3.10) or by an explicit recompute of the negative balance, which the
    PRD calls for only on chargeback reversal (§3.7).
    """
    total = unsettled_sum(dev["id"])
    if total < 0:
        dev["unpaid_accrual_cents"] = 0
        dev["negative_balance_cents"] = -total
    else:
        dev["unpaid_accrual_cents"] = total
        if recompute_negative_balance:
            dev["negative_balance_cents"] = 0


def developer_purchases(developer_id):
    return [p for p in ordered(db.purchases) if p["developer_id"] == developer_id]


# --------------------------------------------------------------------------
# Tier selection (PRD §3.1)
# --------------------------------------------------------------------------
def select_tier(base_amount):
    candidates = [
        t for t in ordered(db.revenue_share_tiers)
        if t["min_cumulative_base_cents"] <= base_amount
    ]
    if not candidates:
        return DEFAULT_SHARE_BPS
    candidates.sort(
        key=lambda t: (-t["min_cumulative_base_cents"], -t["developer_share_bps"], t["_seq"])
    )
    return candidates[0]["developer_share_bps"]


# --------------------------------------------------------------------------
# Risk score (PRD §3.8)
# --------------------------------------------------------------------------
SCORED_PAYMENT_STATUSES = {"CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED", "CHARGED_BACK"}


def recompute_risk(dev):
    scored = [
        p for p in developer_purchases(dev["id"])
        if p["payment_status"] in SCORED_PAYMENT_STATUSES
    ]
    if dev.get("risk_watch"):
        variant = "ACCELERATED"
        cutoff = clock_now() - days(RISK_WINDOW_DAYS)
        clipped = []
        for p in scored:
            captured = parse_iso(p.get("captured_at")) if p.get("captured_at") else None
            if captured is not None and captured >= cutoff:
                clipped.append(p)
        scored = clipped
    else:
        variant = "STANDARD"

    denom = sum(p["gross_cents"] for p in scored)
    if denom == 0:
        refund_rate = Decimal(0)
        chargeback_rate = Decimal(0)
    else:
        refunded = sum(p.get("refunded_gross_cents", 0) for p in scored)
        charged_back = sum(
            p["gross_cents"] for p in scored if p["payment_status"] == "CHARGED_BACK"
        )
        refund_rate = Decimal(refunded) / Decimal(denom)
        chargeback_rate = Decimal(charged_back) / Decimal(denom)

    strike_factor = min(
        Decimal(1),
        Decimal(dev.get("policy_strike_count", 0)) / Decimal(POLICY_STRIKE_SUSPEND_THRESHOLD),
    )
    raw = (
        Decimal(REFUND_WEIGHT) * refund_rate
        + Decimal(CHARGEBACK_WEIGHT) * chargeback_rate
        + Decimal(STRIKE_WEIGHT) * strike_factor
    )
    dev["risk_score"] = min(100, rhu(raw))
    dev["risk_variant"] = variant


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------
def recompute_batch_totals(batch):
    lines = [l for l in ordered(db.payout_lines) if l["payout_batch_id"] == batch["id"]]
    payable = [l for l in lines if l["status"] == "PAYABLE"]
    batch["total_payable_cents"] = sum(l["payout_amount_cents"] for l in payable)
    batch["total_withholding_cents"] = sum(l["withholding_cents"] for l in payable)
    touch(batch)


def suspend_developer(dev):
    """ACTIVE -> SUSPENDED with the full cascade (PRD §3.2)."""
    dev["status"] = "SUSPENDED"
    dev["risk_watch"] = True
    dev["payout_hold"] = True
    recompute_risk(dev)
    touch(dev)

    affected_batches = []
    for line in ordered(db.payout_lines):
        if line["developer_id"] != dev["id"] or line["status"] != "PAYABLE":
            continue
        batch = db.payout_batches.get(line["payout_batch_id"])
        if batch is None or batch["status"] not in ("CALCULATED", "PENDING_APPROVAL"):
            continue
        line["status"] = "HELD_DEVELOPER"
        line["payout_amount_cents"] = 0
        touch(line)
        if batch["id"] not in [b["id"] for b in affected_batches]:
            affected_batches.append(batch)
    for batch in affected_batches:
        recompute_batch_totals(batch)


def delist_app(app):
    """App -> DELISTED with the full cascade (PRD §3.3)."""
    app["status"] = "DELISTED"
    app["policy_strike_count"] = app.get("policy_strike_count", 0) + 1
    touch(app)

    for plan in ordered(db.pricing_plans):
        if plan["app_id"] == app["id"] and plan["status"] == "ACTIVE":
            plan["status"] = "RETIRED"
            touch(plan)

    dev = db.developers.get(app["developer_id"])
    if dev is not None:
        dev["policy_strike_count"] = dev.get("policy_strike_count", 0) + 1
        touch(dev)
        if (
            dev["policy_strike_count"] >= POLICY_STRIKE_SUSPEND_THRESHOLD
            and dev["status"] == "ACTIVE"
        ):
            suspend_developer(dev)


# --------------------------------------------------------------------------
# Purchase-level calculations
# --------------------------------------------------------------------------
def executed_refunds(purchase_id):
    return [
        r for r in ordered(db.refunds)
        if r["purchase_id"] == purchase_id and r["status"] == "EXECUTED"
    ]
