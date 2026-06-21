"""Pricing & turnaround & loyalty calculations (PRD §3.2, §3.6, §3.7).

All money in integer cents; rates/discounts in basis points (1bp = 1/10000).
Rounding is half-up and applied only at the pinned points each rule names.
"""

from datetime import date, timedelta
from decimal import Decimal

import db
from services.common import round_half_up, round_half_up_1dp, bps_apply

# Preflight minimums (calc preflight_evaluation constants, PRD §3.3).
MIN_DPI = 150
MIN_BLEED_MM = 3

# Loyalty score weights & tier thresholds (calc committed_loyalty_score, PRD §3.7).
W_COUNT = Decimal("1.0")
W_SPEND = Decimal("0.5")
SILVER_THRESHOLD = 3.0
GOLD_THRESHOLD = 6.0

# Loyalty discount basis points by committed tier (PRD §3.6).
LOYALTY_DISCOUNT_BPS = {"NONE": 0, "SILVER": 500, "GOLD": 1000}


# ---------------------------------------------------------------------------
# Line price (estimate / final share identical arithmetic — PRD §3.2, §3.6).
# ---------------------------------------------------------------------------
def select_tier_discount_bps(product_id, quantity):
    """Greatest min_quantity tier with min_quantity <= quantity; else 0 (PRD §3.2)."""
    best = None
    for tier in db.pricing_tiers.values():
        if tier["product_id"] != product_id:
            continue
        if tier["min_quantity"] <= quantity:
            if best is None or tier["min_quantity"] > best["min_quantity"]:
                best = tier
    return best["discount_bps"] if best is not None else 0


def compute_line_price(product, quantity, finishing_codes):
    """Tier-and-finishing line price in cents (the shared estimate/final body).

    Step 1 — tier discount, round-half-up at the discounted-unit step ONLY, then
             integer-multiply by quantity (round-then-multiply, pinned).
    Step 2 — finishing: PER_UNIT contributes surcharge*quantity, FLAT once.
    Step 3 — line subtotal = base + finishing (no rush here).
    """
    tier_discount_bps = select_tier_discount_bps(product["id"], quantity)
    discounted_unit_cents = round_half_up(
        Decimal(product["base_unit_price_cents"])
        * Decimal(10000 - tier_discount_bps)
        / Decimal(10000)
    )
    base_cents = discounted_unit_cents * quantity

    finishing_cents = 0
    options = _finishing_by_code(product["id"])
    for code in finishing_codes:
        opt = options.get(code)
        if opt is None:
            continue  # belongs-to-product is validated before pricing
        if opt["surcharge_kind"] == "PER_UNIT":
            finishing_cents += opt["surcharge_cents"] * quantity
        else:  # FLAT
            finishing_cents += opt["surcharge_cents"]

    return base_cents + finishing_cents


def _finishing_by_code(product_id):
    out = {}
    for opt in db.finishing_options.values():
        if opt["product_id"] == product_id:
            out[opt["code"]] = opt
    return out


def compute_rush_surcharge(final_line_cents, service_level, shop):
    """Rush surcharge captured at lock: final*rush_bps/10000 half-up, 0 STANDARD."""
    if service_level == "RUSH":
        return bps_apply(final_line_cents, shop["rush_surcharge_bps"])
    return 0


def production_units(product, quantity):
    """quantity * Product.unit_size (PRD §3.2)."""
    return quantity * product["unit_size"]


# ---------------------------------------------------------------------------
# Turnaround date per line (calc line_turnaround, PRD §3.6).
# ---------------------------------------------------------------------------
def _parse_anchor(current_utc_iso):
    """Return (calendar date, hour-of-day UTC) of the pinned clock instant."""
    s = current_utc_iso
    anchor_date = date.fromisoformat(s[0:10])  # YYYY-MM-DD
    hour = int(s[11:13]) if len(s) >= 13 else 0
    return anchor_date, hour


def line_turnaround_date(current_utc_iso, service_level, shop):
    """Promised-ready date for one line (whole calendar-day arithmetic)."""
    anchor_date, anchor_hour = _parse_anchor(current_utc_iso)
    if service_level == "STANDARD":
        ready = anchor_date + timedelta(days=shop["standard_turnaround_days"])
    else:  # RUSH
        ready = anchor_date + timedelta(days=shop["rush_turnaround_days"])
        if anchor_hour >= shop["rush_cutoff_hour_utc"]:
            ready = ready + timedelta(days=1)
    return ready.isoformat()


# ---------------------------------------------------------------------------
# Loyalty discount by committed tier (calc order_loyalty_discount, PRD §3.6).
# ---------------------------------------------------------------------------
def loyalty_discount_cents(subtotal_cents, loyalty_tier):
    pct_bps = LOYALTY_DISCOUNT_BPS.get(loyalty_tier, 0)
    if pct_bps == 0:
        return 0
    return bps_apply(subtotal_cents, pct_bps)


# ---------------------------------------------------------------------------
# Committed loyalty score & tier (calc committed_loyalty_score, PRD §3.7).
# ---------------------------------------------------------------------------
def compute_loyalty_score(completed_order_count, lifetime_paid_cents):
    raw = (W_COUNT * Decimal(completed_order_count)
           + W_SPEND * (Decimal(lifetime_paid_cents) / Decimal(10000)))
    return round_half_up_1dp(raw)


def tier_for_score(score):
    if score >= GOLD_THRESHOLD:
        return "GOLD"
    if score >= SILVER_THRESHOLD:
        return "SILVER"
    return "NONE"
