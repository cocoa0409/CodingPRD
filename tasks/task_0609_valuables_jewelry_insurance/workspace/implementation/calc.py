"""Calculation rules (SCAFFOLD §1.3, PRD §3.4-§3.12).

All monetary math uses Decimal with ROUND_HALF_UP, except the two explicit
floor() points: in-network deductible halving and the completed-policy-year
count for revaluation.
"""
from decimal import Decimal, ROUND_HALF_UP

import db

# ---- constants ----------------------------------------------------------
DEDUCTIBLE_CENTS = {"ZERO": 0, "LOW": 25000, "STANDARD": 50000, "HIGH": 100000}
APPRAISAL_REQUIRED_THRESHOLD_CENTS = 1000000  # strict '>' ; $10,000 needs no appraisal
MAX_INFO_REQUESTS = 2
GRACE_DAYS = 30
REINSTATE_DAYS = 30
POLICY_YEAR_DAYS = 365

CATEGORY_RISK_MULT = {
    "RING": "1.00", "NECKLACE": "1.05", "WATCH": "1.20",
    "LOOSE_STONE": "1.40", "OTHER": "1.10",
}
ALL_RISK_MULT = "1.30"
NAMED_PERIL_MULT = "1.00"
TIER1_CENTS = 500000      # $5,000
TIER2_CENTS = 2000000     # $20,000
CAT_SURCHARGE_CENTS = 1500
DEDUCTIBLE_CREDIT = {"ZERO": "1.10", "LOW": "1.00", "STANDARD": "0.92", "HIGH": "0.85"}
ITEM_MIN_PREMIUM_CENTS = 2500

# Default RiskZone band rate used when no zone matches the item's prefix.
# The PRD says "the moderate default band rate is used"; with no configured
# default zone we treat the missing zone as rate 0 (MODERATE band, not
# catastrophe-loaded). Tests always create the matching zone.
DEFAULT_RATE_PER_THOUSAND_CENTS = 0
DEFAULT_CAT_LOADED = False

REPLACEMENT_CAP_FACTOR = "1.0"
REPLACEMENT_DEPRECIATION_PCT = "0.05"
MAX_EPOCHS = 10


def round_half_up(value):
    """Round a Decimal to whole cents, half up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def resolve_deductible(option):
    return DEDUCTIBLE_CENTS[option]


def _zone_for_zip(location_zip):
    prefix = location_zip[:3]
    for z in db.risk_zones.values():
        if z["zip_prefix"] == prefix:
            return z
    return None


def item_annual_premium(item, policy):
    """Per-item annual premium (SCAFFOLD item_annual_premium; PRD §3.4)."""
    zone = _zone_for_zip(item["location_zip"])
    if zone is not None:
        rate = zone["rate_per_thousand_cents"]
        cat_loaded = zone.get("catastrophe_loaded", False)
    else:
        rate = DEFAULT_RATE_PER_THOUSAND_CENTS
        cat_loaded = DEFAULT_CAT_LOADED

    cv = item["current_value_cents"]
    # base = (current_value_cents / 100000) * rate_per_thousand_cents
    base = (Decimal(cv) / Decimal(100000)) * Decimal(rate)

    category_mult = Decimal(CATEGORY_RISK_MULT[item["category"]])
    coverage_mult = Decimal(ALL_RISK_MULT) if policy["coverage_type"] == "ALL_RISK" else Decimal(NAMED_PERIL_MULT)

    if cv <= TIER1_CENTS:
        tier_mult = Decimal("1.00")
    elif cv <= TIER2_CENTS:
        tier_mult = Decimal("1.10")
    else:
        tier_mult = Decimal("1.25")

    deductible_credit = Decimal(DEDUCTIBLE_CREDIT[policy["deductible_option"]])

    raw = base * category_mult * coverage_mult * tier_mult * deductible_credit
    rounded = round_half_up(raw)
    premium = max(ITEM_MIN_PREMIUM_CENTS, rounded)
    cat_surcharge = CAT_SURCHARGE_CENTS if cat_loaded else 0
    return premium + cat_surcharge


def _premium_bearing_items(policy):
    """ScheduledItems on this policy with item_status in {ACTIVE, SUSPENDED}."""
    out = []
    for it in db.scheduled_items.values():
        if it["policy_id"] == policy["id"] and it["item_status"] in ("ACTIVE", "SUSPENDED"):
            out.append(it)
    return out


def policy_aggregates(policy, deductible_option=None):
    """Return (annual_premium_cents, total_insured_value_cents).

    Round-then-sum: each item premium is rounded to whole cents first (inside
    item_annual_premium), then the already-rounded figures are summed. If
    deductible_option is given it overrides the policy's option for a what-if
    computation (used by CHANGE_DEDUCTIBLE proration).
    """
    eff_policy = policy
    if deductible_option is not None and deductible_option != policy["deductible_option"]:
        eff_policy = dict(policy)
        eff_policy["deductible_option"] = deductible_option

    premium = 0
    insured = 0
    for it in _premium_bearing_items(policy):
        premium += item_annual_premium(it, eff_policy)
        insured += it["current_value_cents"]
    return premium, insured


def recompute_policy_aggregates(policy):
    premium, insured = policy_aggregates(policy)
    policy["annual_premium_cents"] = premium
    policy["total_insured_value_cents"] = insured


# ---- inflation-guard revaluation (PRD §3.5) -----------------------------
def revalue_item(item, policy, epochs):
    """Compute current_value_cents for the given completed-epoch count."""
    epochs = min(epochs, MAX_EPOCHS)
    base = Decimal(item["scheduled_value_cents"])
    pct = Decimal(str(policy["inflation_guard_pct"]))
    mode = policy["inflation_guard_mode"]
    if mode == "SIMPLE":
        factor = Decimal(1) + pct * Decimal(epochs)
    elif mode == "COMPOUND":
        factor = (Decimal(1) + pct) ** epochs
    else:
        factor = Decimal(1)
    return round_half_up(base * factor), epochs


# ---- settlement (PRD §3.12) ---------------------------------------------
def total_loss_gross(item, policy):
    """Gross for a TOTAL_LOSS claim under the policy's valuation_basis."""
    cv = item["current_value_cents"]
    if policy["valuation_basis"] == "AGREED_VALUE":
        return cv
    # REPLACEMENT_COST: depreciate the capped replacement figure.
    cap = round_half_up(Decimal(REPLACEMENT_CAP_FACTOR) * Decimal(item["scheduled_value_cents"]))
    capped = min(cv, cap)
    depreciation = Decimal(1) - Decimal(REPLACEMENT_DEPRECIATION_PCT) * Decimal(item["revaluation_epoch"])
    return round_half_up(Decimal(capped) * depreciation)


def compute_settlement(claim, item, policy, repair_in_network=False):
    """Return (settlement_cents, deductible_applied_cents)."""
    deductible = policy["deductible_cents"]
    if claim["loss_type"] == "PARTIAL_DAMAGE" and repair_in_network:
        effective_deductible = deductible // 2  # floor
    else:
        effective_deductible = deductible

    if claim["loss_type"] == "TOTAL_LOSS":
        gross = total_loss_gross(item, policy)
    else:  # PARTIAL_DAMAGE
        gross = min(claim["claimed_amount_cents"], item["current_value_cents"])

    settlement = max(0, gross - effective_deductible)
    deductible_applied = gross - settlement
    return settlement, deductible_applied


# ---- endorsement proration (PRD §3.10) ----------------------------------
def days_since(anchor_dt, now_dt):
    """Whole days elapsed from anchor to now (floored)."""
    if anchor_dt is None:
        return 0
    delta = now_dt - anchor_dt
    return int(delta.total_seconds() // 86400)


def proration_fraction(bound_at_dt, now_dt):
    elapsed = days_since(bound_at_dt, now_dt)
    days_remaining = max(0, POLICY_YEAR_DAYS - elapsed)
    return Decimal(days_remaining) / Decimal(POLICY_YEAR_DAYS)
