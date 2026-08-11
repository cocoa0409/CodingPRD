"""Calculation rules (SCAFFOLD §1.3 / PRD §3.8, §3.2, §3.9, §3.1).

Money is integer cents; fractional intermediates round HALF-UP, per line
first, then summed (pinned round-then-sum order, PRD §2.7).
"""

import math
from decimal import Decimal, ROUND_HALF_UP

import clocktime
import db

# --- settlement_valuation constants ---------------------------------------
BASE_VALUE_CENTS = {
    "LAPTOP": 40000, "DESKTOP": 25000, "SERVER": 120000, "PHONE": 15000,
    "TABLET": 18000, "MONITOR": 8000, "BATTERY": 0, "OTHER": 5000,
}
GRADE_MULT = {
    "A": Decimal("1.0"), "B": Decimal("0.7"),
    "C": Decimal("0.4"), "D": Decimal("0.1"),
}
COMMISSION_RATE = {
    "STANDARD": Decimal("0.15"), "VOLUME": Decimal("0.15"),
    "ENTERPRISE": Decimal("0.10"),
}

# --- item_recycling_fee constants ------------------------------------------
CATEGORY_BASE_FEE_CENTS = {
    "LAPTOP": 800, "DESKTOP": 1000, "SERVER": 2500, "PHONE": 300,
    "TABLET": 400, "MONITOR": 1200, "BATTERY": 1500, "OTHER": 900,
}
WEIGHT_PER_KG_RATE = {"LIGHT": 120, "MID": 90, "HEAVY": 60}
HAZMAT_SURCHARGE_CENTS = 2000
SANITIZATION_FEE_CENTS = {
    "CRYPTO_ERASE": 500, "NIST_CLEAR": 700,
    "NIST_PURGE": 1000, "PHYSICAL_DESTROY": 1500,
}
PICKUP_FEE_CENTS = 15000

# --- settlement_net_rebate constants ---------------------------------------
REBATE_RATE = {"GOLD": Decimal("0.05"), "SILVER": Decimal("0.02"), "NONE": Decimal("0.0")}
GOLD_FLOOR_CENTS = 500000
SILVER_FLOOR_CENTS = 100000

# --- recycler_selection_score constants ------------------------------------
CERT_HORIZON_DAYS = 365
VOLUME_SATURATION_KG = 10000
VIOLATION_SATURATION = 10

# --- account_tier_threshold constants --------------------------------------
VOLUME_THRESHOLD_KG = Decimal("1000")
ENTERPRISE_THRESHOLD_KG = Decimal("5000")
TIER_RANK = {"STANDARD": 0, "VOLUME": 1, "ENTERPRISE": 2}

CATEGORIES = {"LAPTOP", "DESKTOP", "SERVER", "PHONE", "TABLET", "MONITOR", "BATTERY", "OTHER"}
GRADES = {"A", "B", "C", "D"}
SANITIZATION_METHODS = {"CRYPTO_ERASE", "NIST_CLEAR", "NIST_PURGE", "PHYSICAL_DESTROY"}
TIERS = {"STANDARD", "VOLUME", "ENTERPRISE"}


def round_cents(value):
    """round_half_up to whole integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_2dp(value):
    """round_half_up to two decimal places; returned as float for JSON."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Valuation (QUOTE / FINAL variants)
# ---------------------------------------------------------------------------

def quote_estimate_cents(item):
    """Catalog estimate for an unsold RESALE/REFURB-routed item."""
    return round_cents(BASE_VALUE_CENTS[item["category"]] * GRADE_MULT[item["declared_grade"]])


def final_net_proceeds(sale_price_cents, tier):
    """Per-line final value at sell time: sale minus round_half_up commission."""
    commission = round_cents(Decimal(sale_price_cents) * COMMISSION_RATE[tier])
    return sale_price_cents - commission


def settlement_gross(manifest_items, variant):
    total = 0
    for it in manifest_items:
        if variant == "QUOTE":
            if it["disposition"] not in ("RESALE", "REFURB"):
                continue
            if it["processing_status"] == "SOLD":
                total += it["final_value_cents"]
            else:
                total += quote_estimate_cents(it)
        else:  # FINAL: only COMPLETE items at realized value
            if it["processing_status"] != "COMPLETE":
                continue
            if it["disposition"] in ("RESALE", "REFURB"):
                total += it["final_value_cents"]
    return total


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------

def weight_tier(weight_kg):
    if weight_kg < Decimal("5.0"):
        return "LIGHT"
    if weight_kg <= Decimal("20.0"):
        return "MID"
    return "HEAVY"


def recycling_line_fee_cents(item):
    """Category base + per-kg weight charge + hazmat surcharge (integer cents)."""
    base = CATEGORY_BASE_FEE_CENTS[item["category"]]
    weight_charge = round_cents(item["weight_kg"] * WEIGHT_PER_KG_RATE[weight_tier(item["weight_kg"])])
    hazmat = HAZMAT_SURCHARGE_CENTS if item["hazmat_flag"] else 0
    return base + weight_charge + hazmat


def latest_verified_sanitization(item_id):
    verified = [s for s in db.sanitizations.values()
                if s["item_id"] == item_id and s["status"] == "VERIFIED"]
    if not verified:
        return None
    verified.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return verified[-1]


def sanitization_fee_cents(item, variant):
    """One sanitization fee per data-bearing item. QUOTE assumes NIST_CLEAR;
    FINAL uses the latest VERIFIED method (NIST_CLEAR fallback when none)."""
    if not item["data_bearing"]:
        return 0
    if variant == "FINAL":
        rec = latest_verified_sanitization(item["id"])
        if rec is not None:
            return SANITIZATION_FEE_CENTS[rec["method"]]
    return SANITIZATION_FEE_CENTS["NIST_CLEAR"]


def settlement_fees(manifest, manifest_items, variant):
    total = 0
    for it in manifest_items:
        if it["disposition"] == "RECYCLE":
            if variant == "FINAL" and it["processing_status"] != "COMPLETE":
                continue
            total += recycling_line_fee_cents(it)
    for it in manifest_items:
        if variant == "FINAL" and it["processing_status"] != "COMPLETE":
            continue
        total += sanitization_fee_cents(it, variant)
    if manifest["mode"] == "PICKUP":
        total += PICKUP_FEE_CENTS
    return total


# ---------------------------------------------------------------------------
# Rebate + net (pinned evaluation order: gross -> fees -> pre-rebate net ->
# tier keyed on pre-rebate net -> rebate -> net)
# ---------------------------------------------------------------------------

def net_rebate(gross_cents, fees_cents):
    pre_rebate_net = gross_cents - fees_cents
    if pre_rebate_net >= GOLD_FLOOR_CENTS:
        tier = "GOLD"
    elif pre_rebate_net >= SILVER_FLOOR_CENTS:
        tier = "SILVER"
    else:
        tier = "NONE"
    if pre_rebate_net > 0:
        rebate = round_cents(Decimal(pre_rebate_net) * REBATE_RATE[tier])
    else:
        rebate = 0
    return rebate, pre_rebate_net + rebate


def compute_settlement_figures(manifest, manifest_items, variant):
    gross = settlement_gross(manifest_items, variant)
    fees = settlement_fees(manifest, manifest_items, variant)
    rebate, net = net_rebate(gross, fees)
    return {
        "gross_buyback_cents": gross,
        "total_fees_cents": fees,
        "volume_rebate_cents": rebate,
        "net_amount_cents": net,
    }


# ---------------------------------------------------------------------------
# Recycler selection score + selector policy
# ---------------------------------------------------------------------------

def active_policy():
    for p in db.policies.values():
        if p["is_active"]:
            return p
    return None


def recycler_risk_score(recycler, policy=None):
    """2dp score against the ACTIVE policy weights; None when no policy active."""
    if policy is None:
        policy = active_policy()
    if policy is None:
        return None
    delta_seconds = (recycler["certification_expires_at"] - clocktime.now()).total_seconds()
    days_remaining = math.floor(delta_seconds / 86400)
    cert_freshness = min(1.0, max(0.0, days_remaining / CERT_HORIZON_DAYS))
    volume_factor = min(1.0, float(recycler["total_processed_kg"]) / VOLUME_SATURATION_KG)
    violation_free = max(0.0, 1.0 - recycler["violation_count"] / VIOLATION_SATURATION)
    score = 100.0 * (
        float(policy["weight_cert_freshness"]) * cert_freshness
        + float(policy["weight_volume"]) * volume_factor
        + float(policy["weight_violations"]) * violation_free
    )
    return round_2dp(score)


def select_recycler(scheduled_delivery_date):
    """Eligibility: certification strictly valid at the delivery date.
    Ranking: risk_score DESC, total_processed_kg DESC, created_at ASC
    (never id)."""
    eligible = [r for r in db.recyclers.values()
                if r["certification_expires_at"] > scheduled_delivery_date]
    if not eligible:
        return None
    policy = active_policy()

    def key(r):
        score = recycler_risk_score(r, policy)
        return (
            -(score if score is not None else -1.0),   # risk_score DESC
            -float(r["total_processed_kg"]),            # volume DESC
            r["created_at"],                            # created_at ASC
            r["_seq"],
        )

    eligible.sort(key=key)
    return eligible[0]


# ---------------------------------------------------------------------------
# Tier threshold
# ---------------------------------------------------------------------------

def apply_tier_threshold(account):
    """Never downgrades; boundaries inclusive (exactly 1000.0 -> VOLUME)."""
    lifetime = account["lifetime_diverted_kg"]
    if lifetime >= ENTERPRISE_THRESHOLD_KG:
        target = "ENTERPRISE"
    elif lifetime >= VOLUME_THRESHOLD_KG:
        target = "VOLUME"
    else:
        target = "STANDARD"
    if TIER_RANK[target] > TIER_RANK[account["tier"]]:
        account["tier"] = target


# ---------------------------------------------------------------------------
# Sustainability metrics
# ---------------------------------------------------------------------------

def sustainability_report(account_id):
    account_items = [i for i in db.items.values()
                     if db.manifests.get(i["manifest_id"], {}).get("account_id") == account_id]
    total_items = len(account_items)
    total_weight = sum((i["weight_kg"] for i in account_items), Decimal("0"))
    complete_items = [i for i in account_items if i["processing_status"] == "COMPLETE"]
    diverted_weight = sum((i["weight_kg"] for i in complete_items), Decimal("0"))
    if total_weight > 0:
        rate = round_2dp(Decimal(100) * diverted_weight / total_weight)
    else:
        rate = 0.0
    resale_proceeds = sum(
        i["final_value_cents"] for i in complete_items
        if i["disposition"] in ("RESALE", "REFURB")
    )
    recycling_fees = sum(
        recycling_line_fee_cents(i) + sanitization_fee_cents(i, "FINAL")
        for i in complete_items if i["disposition"] == "RECYCLE"
    )
    item_ids = {i["id"] for i in account_items}
    certificates_issued = sum(
        1 for c in db.certificates.values()
        if c["cert_type"] == "DATA_DESTRUCTION"
        and c["status"] == "ISSUED"
        and c.get("item_id") in item_ids
    )
    return {
        "total_items": total_items,
        "total_weight_kg": float(total_weight),
        "diverted_weight_kg": float(diverted_weight),
        "diversion_rate_pct": rate,
        "resale_proceeds_cents": resale_proceeds,
        "recycling_fees_cents": recycling_fees,
        "certificates_issued": certificates_issued,
    }
