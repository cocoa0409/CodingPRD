"""Calculation rules from scaffold section 1.3."""
import math
from decimal import Decimal, ROUND_HALF_UP

# Freight tier constants
TIER1_MAX_MILES = 25
TIER1_FLAT_CENTS = 9500
TIER2_MAX_MILES = 75
TIER2_FLAT_CENTS = 19500
TIER2_PER_MILE_CENTS = 320
TIER3_PER_MILE_CENTS = 480
FUEL_SURCHARGE_BP = 750

# Restock constants
RESTOCK_FREE_DAYS = 7
RESTOCK_FULL_BUNDLE_BP = 1500
RESTOCK_PARTIAL_BUNDLE_BP = 2500

# Special-order lead time
MIN_FRAMING_PCT_FOR_RATED = 30

# Per-sheet weight lookup (lbs) keyed by thickness.
# PRD references a "per-sheet weight lookup for that board" without tabulating
# values; we use a deterministic lookup keyed by thickness.
SHEET_WEIGHT_LBS = {
    "1/2": 40,
    "5/8": 50,
    "3/4": 60,
}

RATED_KINDS = {"FIRE_RATED", "MOISTURE_RATED"}


def effective_waste_pct_bp(takeoff, account):
    override = takeoff.get("waste_pct_bp_override")
    if override is not None:
        return override
    return account["default_waste_pct_bp"]


def compute_waste_sheets(sheet_count, waste_bp):
    """ceil(sheet_count * waste_bp / 10000)"""
    return math.ceil(sheet_count * waste_bp / 10000)


def compute_bundle_count(sheet_count, waste_sheets, sheets_per_bundle):
    return math.ceil((sheet_count + waste_sheets) / sheets_per_bundle)


def compute_line_cents(bundle_count, sheets_per_bundle, unit_price_cents):
    return bundle_count * sheets_per_bundle * unit_price_cents


def freight_tier_cents(distance_miles, final=False):
    d = distance_miles
    if d <= TIER1_MAX_MILES:
        freight = TIER1_FLAT_CENTS
    elif d <= TIER2_MAX_MILES:
        freight = TIER2_FLAT_CENTS + (d - TIER1_MAX_MILES) * TIER2_PER_MILE_CENTS
    else:
        freight = (
            TIER2_FLAT_CENTS
            + (TIER2_MAX_MILES - TIER1_MAX_MILES) * TIER2_PER_MILE_CENTS
            + (d - TIER2_MAX_MILES) * TIER3_PER_MILE_CENTS
        )
    if final:
        # Apply fuel surcharge, round half-up to whole cents
        val = Decimal(freight) * Decimal(10000 + FUEL_SURCHARGE_BP) / Decimal(10000)
        freight = int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return freight


def sheet_weight_lbs(bundle_count, sheets_per_bundle, thickness_in):
    return bundle_count * sheets_per_bundle * SHEET_WEIGHT_LBS.get(thickness_in, 50)


def restock_fee_and_credit(material_value_cents, days_since_stocked, loose_sheets_returned):
    if days_since_stocked <= RESTOCK_FREE_DAYS:
        rate_bp = 0
    elif loose_sheets_returned == 0:
        rate_bp = RESTOCK_FULL_BUNDLE_BP
    else:
        rate_bp = RESTOCK_PARTIAL_BUNDLE_BP
    fee = int(
        (Decimal(material_value_cents) * Decimal(rate_bp) / Decimal(10000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    credit = material_value_cents - fee
    return fee, credit
