"""Calculations: tier config, warranty coverage, refund, settlement, exposure, ledgers."""
from decimal import Decimal, ROUND_HALF_UP

import store
from store import touch
from util import add_calendar_months, parse_dt

TIER_CONFIG = {
    "BASIC": {
        "included_claims_per_year": 2,
        "extended_warranty_bonus_months": 0,
        "prorate_refunds": True,
        "shipping_reimbursement_pct": Decimal("0.0"),
        "concierge_fee_pct": Decimal("0.10"),
    },
    "PLUS": {
        "included_claims_per_year": 5,
        "extended_warranty_bonus_months": 6,
        "prorate_refunds": False,
        "shipping_reimbursement_pct": Decimal("0.5"),
        "concierge_fee_pct": Decimal("0.05"),
    },
    "PREMIUM": {
        "included_claims_per_year": 20,
        "extended_warranty_bonus_months": 12,
        "prorate_refunds": False,
        "shipping_reimbursement_pct": Decimal("1.0"),
        "concierge_fee_pct": Decimal("0.0"),
    },
}

SEVERITY_WEIGHT = {"LOW": 1, "HIGH": 3, "CRITICAL": 5}

OPEN_MATCH_STATES = {"MATCHED", "ACKNOWLEDGED"}
ACTIVE_CLAIM_STATES = {"DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_DOCS", "APPROVED"}


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_active_subscription(household_id):
    """Status==ACTIVE and half-open [period_start, period_end) contains the clock."""
    clock = store.get_clock()
    for s in store.subscriptions.values():
        if s["household_id"] != household_id or s["status"] != "ACTIVE":
            continue
        ps = parse_dt(s["period_start"])
        pe = parse_dt(s["period_end"])
        if ps <= clock < pe:
            return s
    return None


def resolve_tier_subscription(household_id):
    """Subscription used for tier-driven money math; strict active, else any ACTIVE-status."""
    sub = get_active_subscription(household_id)
    if sub is not None:
        return sub
    candidates = [
        s for s in store.subscriptions.values()
        if s["household_id"] == household_id and s["status"] == "ACTIVE"
    ]
    if candidates:
        return sorted(candidates, key=lambda r: r["_seq"])[0]
    return None


def warranty_expires_at(product):
    sub = get_active_subscription(product["household_id"])
    bonus = TIER_CONFIG[sub["tier"]]["extended_warranty_bonus_months"] if sub else 0
    effective_months = product["warranty_months"] + bonus
    return add_calendar_months(parse_dt(product["purchase_date"]), effective_months)


def has_open_recall_match(product_id):
    for m in store.recall_matches.values():
        if m["product_id"] == product_id and m["status"] in OPEN_MATCH_STATES:
            return True
    return False


def coverage_status(product):
    if has_open_recall_match(product["id"]):
        return "COVERED_BY_RECALL"
    clock = store.get_clock()
    exp = warranty_expires_at(product)
    if clock.date() <= exp.date():
        return "UNDER_WARRANTY"
    return "EXPIRED"


def recompute_recall_exposure(household):
    hid = household["id"]
    weighted = 0
    count = 0
    for m in store.recall_matches.values():
        if m["status"] not in OPEN_MATCH_STATES:
            continue
        prod = store.products.get(m["product_id"])
        if prod is not None and prod["household_id"] == hid:
            count += 1
            weighted += m["severity_weight"]
    if household["exposure_scoring_mode"] == "WEIGHTED":
        household["recall_exposure_score"] = weighted
    else:
        household["recall_exposure_score"] = count
    touch(household)


def recompute_active_claim_count(household):
    hid = household["id"]
    count = 0
    for c in store.claims.values():
        if c["status"] not in ACTIVE_CLAIM_STATES:
            continue
        prod = store.products.get(c["product_id"])
        if prod is not None and prod["household_id"] == hid:
            count += 1
    household["active_claim_count"] = count
    touch(household)


def compute_refund(product, tier):
    """Returns (refund_variant, refund_amount_cents)."""
    cfg = TIER_CONFIG[tier]
    if not cfg["prorate_refunds"]:
        return "FULL", product["purchase_price_cents"]
    exp = warranty_expires_at(product)
    purchase = parse_dt(product["purchase_date"])
    clock = store.get_clock()
    total_days = (exp.date() - purchase.date()).days
    elapsed_days = (clock.date() - purchase.date()).days
    remaining_days = max(0, total_days - elapsed_days)
    if total_days <= 0:
        return "PRORATED", 0
    amount = round_half_up(Decimal(product["purchase_price_cents"]) * Decimal(remaining_days) / Decimal(total_days))
    return "PRORATED", amount


def compute_settlement(refund_amount_cents, shipping_cost_cents, tier):
    """Round each component independently, then combine. Returns dict of components."""
    cfg = TIER_CONFIG[tier]
    refund_component = refund_amount_cents or 0
    shipping_reimbursement = round_half_up(Decimal(shipping_cost_cents) * cfg["shipping_reimbursement_pct"])
    concierge_fee = round_half_up(Decimal(refund_component) * cfg["concierge_fee_pct"])
    settlement_total = refund_component + shipping_reimbursement - concierge_fee
    return {
        "shipping_reimbursement_cents": shipping_reimbursement,
        "concierge_fee_cents": concierge_fee,
        "settlement_total_cents": settlement_total,
    }
