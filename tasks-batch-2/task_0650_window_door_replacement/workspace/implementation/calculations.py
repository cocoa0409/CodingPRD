"""Deterministic calculations (SCAFFOLD §1.3 / PRD §3). All money in integer cents.

round_half_up via Decimal(ROUND_HALF_UP). Never use float for money rounding.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# --- opening_unit_price ---
BASE_RATE_CENTS_PER_SQFT = {
    "DOUBLE_HUNG": 4200,
    "CASEMENT": 4800,
    "PICTURE": 3600,
    "SLIDING_PATIO_DOOR": 5200,
    "ENTRY_DOOR": 6000,
}
GLASS_UPLIFT_CENTS_PER_SQFT = {
    "STANDARD": 0,
    "LOWE_DUAL": 900,
    "LOWE_TRIPLE": 1800,
}
U_FACTOR_BY_GLASS = {
    "STANDARD": 0.40,
    "LOWE_DUAL": 0.27,
    "LOWE_TRIPLE": 0.20,
}
ENERGY_STAR_U_MAX = Decimal("0.30")

WINDOW_TYPES = {"DOUBLE_HUNG", "CASEMENT", "PICTURE"}
DOOR_TYPES = {"ENTRY_DOOR", "SLIDING_PATIO_DOOR"}

# --- quote_estimate_total ---
TIER1_THRESHOLD_CENTS = 2000000
TIER2_THRESHOLD_CENTS = 4000000
TIER1_PCT = Decimal("0.05")
TIER2_PCT = Decimal("0.10")
INSTALL_FLAT_CENTS = 35000
INSTALL_PER_OPENING_CENTS = 1500

# --- rebate_25c ---
CREDIT_RATE = Decimal("0.30")
WINDOW_ANNUAL_CAP_CENTS = 60000
DOOR_TOTAL_CAP_CENTS = 50000

# --- lead_time_days ---
BASE_BY_TYPE_DAYS = {
    "DOUBLE_HUNG": 28,
    "CASEMENT": 35,
    "PICTURE": 21,
    "SLIDING_PATIO_DOOR": 49,
    "ENTRY_DOOR": 42,
}
TRIPLE_GLAZE_SURCHARGE_DAYS = 14

# --- financing ---
APR_TABLE = {
    "LOW": {12: 0, 24: 0, 36: 599, 60: 899},
    "STANDARD": {12: 0, 24: 499, 36: 899, 60: 1299},
    "HIGH": {12: 299, 24: 799, 36: 1199, 60: 1599},
}

# --- service_charge ---
BASE_TRIP_CENTS = 9500
OUT_OF_WARRANTY_SURCHARGE_CENTS = 5000
WARRANTY_WINDOW_DAYS = 730

# --- referral_reward ---
REWARD_RATE = Decimal("0.02")
REWARD_CAP_CENTS = 50000

# --- jurisdiction ---
INSPECTION_WINDOW_DAYS = {
    "WEST_STRICT": 7,
    "NORTHEAST_STD": 14,
    "CENTRAL_LIGHT": 30,
}


def round_half_up(value):
    """Round a Decimal to whole cents (integer) using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_opening(product_type, width_in, height_in, glass_package):
    """Returns dict: unit_price_cents, u_factor, energy_qualified."""
    area_sqft = (Decimal(str(width_in)) * Decimal(str(height_in))) / Decimal(144)
    base = BASE_RATE_CENTS_PER_SQFT[product_type]
    uplift = GLASS_UPLIFT_CENTS_PER_SQFT[glass_package]
    raw_cents = area_sqft * Decimal(base + uplift)
    unit_price_cents = round_half_up(raw_cents)
    u_factor = U_FACTOR_BY_GLASS[glass_package]
    energy_qualified = Decimal(str(u_factor)) <= ENERGY_STAR_U_MAX
    return {
        "unit_price_cents": unit_price_cents,
        "u_factor": u_factor,
        "energy_qualified": energy_qualified,
    }


def discount_tier(openings_subtotal_cents):
    if openings_subtotal_cents < TIER1_THRESHOLD_CENTS:
        return "NONE", Decimal("0")
    if openings_subtotal_cents < TIER2_THRESHOLD_CENTS:
        return "TIER1", TIER1_PCT
    return "TIER2", TIER2_PCT


def quote_estimate_total(openings, total_opening_count):
    """Returns dict: openings_subtotal_cents, discount_tier, estimate_total_cents.

    Pinned order: subtotal = sum of already-rounded per-opening prices; discount
    keyed on subtotal then rounded once; install fee flat + per-opening; estimate.
    """
    openings_subtotal_cents = sum(o["unit_price_cents"] for o in openings)
    tier, pct = discount_tier(openings_subtotal_cents)
    discount_cents = round_half_up(Decimal(openings_subtotal_cents) * pct)
    install_fee_cents = INSTALL_FLAT_CENTS + INSTALL_PER_OPENING_CENTS * total_opening_count
    estimate_total_cents = openings_subtotal_cents - discount_cents + install_fee_cents
    return {
        "openings_subtotal_cents": openings_subtotal_cents,
        "discount_tier": tier,
        "estimate_total_cents": estimate_total_cents,
    }


def rebate_25c(openings, agi_band=None, final=False):
    """25C credit over energy_qualified openings, split window/door, each 30%
    rounded then capped. estimate variant: ignores agi_band over all qualified.
    final variant: agi_band HIGH zeroes the credit; otherwise same.
    """
    if final and agi_band == "HIGH":
        return 0
    window_qualified = sum(
        o["unit_price_cents"]
        for o in openings
        if o["energy_qualified"] and o["product_type"] in WINDOW_TYPES
    )
    door_qualified = sum(
        o["unit_price_cents"]
        for o in openings
        if o["energy_qualified"] and o["product_type"] in DOOR_TYPES
    )
    window_credit = min(round_half_up(Decimal(window_qualified) * CREDIT_RATE), WINDOW_ANNUAL_CAP_CENTS)
    door_credit_raw = round_half_up(Decimal(door_qualified) * CREDIT_RATE)
    door_credit = min(door_credit_raw, DOOR_TOTAL_CAP_CENTS)
    return window_credit + door_credit


def lead_time_days(openings):
    slowest = max(BASE_BY_TYPE_DAYS[o["product_type"]] for o in openings)
    triple_present = any(o["glass_package"] == "LOWE_TRIPLE" for o in openings)
    surcharge = TRIPLE_GLAZE_SURCHARGE_DAYS if triple_present else 0
    return slowest + surcharge


def financing_monthly_payment(agi_band, term_months, requested_amount_cents):
    """Returns (approved_apr_bps, monthly_payment_cents)."""
    apr_bps = APR_TABLE[agi_band][term_months]
    P = requested_amount_cents
    if apr_bps == 0:
        monthly = math.ceil(P / term_months)
    else:
        r = (Decimal(apr_bps) / Decimal(10000)) / Decimal(12)
        one_plus_r = Decimal(1) + r
        pow_term = one_plus_r ** term_months
        factor = (r * pow_term) / (pow_term - Decimal(1))
        monthly = round_half_up(Decimal(P) * factor)
    return apr_bps, monthly


def service_charge(category, current_clock, project_completed_at):
    """category WARRANTY -> 0; BILLABLE -> base + surcharge if out of warranty."""
    if category == "WARRANTY":
        return 0
    charge = BASE_TRIP_CENTS
    if project_completed_at is not None:
        from clock import add_days
        out_of_warranty = current_clock >= add_days(project_completed_at, WARRANTY_WINDOW_DAYS)
        if out_of_warranty:
            charge += OUT_OF_WARRANTY_SURCHARGE_CENTS
    return charge


def referral_reward(estimate_total_cents):
    raw = round_half_up(Decimal(estimate_total_cents) * REWARD_RATE)
    return min(raw, REWARD_CAP_CENTS)
