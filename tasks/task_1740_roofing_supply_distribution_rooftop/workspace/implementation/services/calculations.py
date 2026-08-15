"""Calculation rules (scaffold Table 3 / PRD 2.6 and section 3).

All money is integer cents; percentage applications round half up at each
step. Bundle counts are whole bundles; estimation ceils per line before
summing; surge tier caps round half down.
"""
from decimal import Decimal, ROUND_CEILING

from db import db
from util import round_half_down_int, round_half_up_int

# takeoff_material_estimate constants
ACCESSORY_COVERAGE_FEET_PER_BUNDLE = 33
ACCESSORY_PRICE_CENTS = 4200

# order_pricing constants
VOLUME_MIN_SUBTOTAL_CENTS = 250000
PREFERRED_DISCOUNT_PCT = 5
VOLUME_DISCOUNT_PCT = 8

# delivery_fee constants
GROUND_FEE_CENTS = 8500
ROOFTOP_FEE_CENTS = 22500
CRANE_FEE_CENTS = 60000
HEAVY_LOAD_BUNDLE_THRESHOLD = 40
PER_BUNDLE_SURCHARGE_CENTS = 350

# return_credit constants
OPENED_CREDIT_PCT = 50
RESTOCKING_FEE_PER_BUNDLE_CENTS = 900

# storm_surge_allocation tier caps (percent of allocation_pool_bundles)
TIER_CAP_PCT = {"VOLUME": 50, "PREFERRED": 35, "STANDARD": 25}


def takeoff_estimate(product, roof_squares, waste_factor_pct, valley_ridge_linear_feet):
    """Per-line ceil, then sum (never sum-then-round). Returns
    (shingle_bundles, accessory_bundles, estimated_bundles, estimated_amount_cents)."""
    squares = Decimal(str(roof_squares))
    waste = Decimal(str(waste_factor_pct))
    bps = Decimal(str(product["bundles_per_square"]))
    adjusted_squares = squares * (Decimal(1) + waste / Decimal(100))
    shingle_bundles = int((adjusted_squares * bps).to_integral_value(rounding=ROUND_CEILING))
    feet = int(valley_ridge_linear_feet or 0)
    accessory_bundles = -(-feet // ACCESSORY_COVERAGE_FEET_PER_BUNDLE) if feet > 0 else 0
    estimated_bundles = shingle_bundles + accessory_bundles
    estimated_amount_cents = (shingle_bundles * int(product["base_price_per_bundle_cents"])
                              + accessory_bundles * ACCESSORY_PRICE_CENTS)
    return shingle_bundles, accessory_bundles, estimated_bundles, estimated_amount_cents


def order_lines_of(order_id):
    return [l for l in db["order_lines"].values() if l["order_id"] == order_id]


def active_surge_event_for_branch(branch_id):
    """The branch's single ACTIVE event (PRD 3.6), if any."""
    candidates = [e for e in db["surge_events"].values()
                  if e["branch_id"] == branch_id and e["status"] == "ACTIVE"]
    if not candidates:
        return None
    candidates.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return candidates[0]


def compute_order_pricing(order, account, branch, surge_event):
    """Pinned evaluation order (PRD 3.4): subtotal -> tier discount keyed on
    pre-discount subtotal -> surge premium -> total. Mutates the order record
    in place (caller mutates version)."""
    lines = order_lines_of(order["id"])
    subtotal = sum(l["quantity_bundles"] * l["unit_price_cents"] for l in lines)
    tier = account["pricing_tier"]
    if tier == "VOLUME":
        pct = VOLUME_DISCOUNT_PCT if subtotal >= VOLUME_MIN_SUBTOTAL_CENTS else PREFERRED_DISCOUNT_PCT
    elif tier == "PREFERRED":
        pct = PREFERRED_DISCOUNT_PCT
    else:
        pct = 0
    discount = round_half_up_int(subtotal * pct, 100)
    if branch["surge_mode"] == "SURGE" and surge_event is not None:
        surge = round_half_up_int(subtotal * int(surge_event["surge_multiplier_pct"]), 100)
    else:
        surge = 0
    total = subtotal - discount + surge + order["delivery_fee_cents"]
    order["subtotal_cents"] = subtotal
    order["discount_cents"] = discount
    order["surge_premium_cents"] = surge
    order["total_cents"] = total


def delivery_fee(equipment_type, bundle_count):
    """Base fee + strict-greater heavy-load surcharge + flat crane fee.
    Returns (fee_cents, crane_fee_cents)."""
    base = GROUND_FEE_CENTS if equipment_type == "GROUND" else ROOFTOP_FEE_CENTS
    surcharge = 0
    if bundle_count > HEAVY_LOAD_BUNDLE_THRESHOLD:
        surcharge = (bundle_count - HEAVY_LOAD_BUNDLE_THRESHOLD) * PER_BUNDLE_SURCHARGE_CENTS
    crane = CRANE_FEE_CENTS if equipment_type == "CRANE" else 0
    return base + surcharge + crane, crane


def return_credit(unit_price_cents, quantity_bundles, opened_bundles):
    """Unopened at full price; opened at 50% (round half up) less 900/bundle
    restocking; floored at zero. Returns (credit_amount_cents, restocking_fee_cents)."""
    unopened = quantity_bundles - opened_bundles
    unopened_credit = unopened * unit_price_cents
    opened_gross = round_half_up_int(opened_bundles * unit_price_cents * OPENED_CREDIT_PCT, 100)
    restocking = opened_bundles * RESTOCKING_FEE_PER_BUNDLE_CENTS
    credit = unopened_credit + opened_gross - restocking
    if credit < 0:
        credit = 0
    return credit, restocking


def tier_cap_bundles(tier, allocation_pool_bundles):
    """Round half down (a fractional bundle of quota is meaningless)."""
    pct = TIER_CAP_PCT.get(tier, TIER_CAP_PCT["STANDARD"])
    return round_half_down_int(allocation_pool_bundles * pct, 100)


def contractor_granted_total(event_id, contractor_account_id):
    """Bundles already granted to this contractor under this event across
    live allocations (binds the tier cap cumulatively)."""
    total = 0
    for a in db["allocations"].values():
        if (a["storm_surge_event_id"] == event_id
                and a["contractor_account_id"] == contractor_account_id
                and a["status"] in ("GRANTED", "PARTIALLY_CONSUMED", "CONSUMED")):
            total += a["granted_bundles"]
    return total


def unconsumed_allocation_for(event_id, contractor_account_id, product_id):
    """Contractor's unconsumed granted bundles for a product under an event."""
    total = 0
    for a in db["allocations"].values():
        if (a["storm_surge_event_id"] == event_id
                and a["contractor_account_id"] == contractor_account_id
                and a["product_id"] == product_id
                and a["status"] in ("GRANTED", "PARTIALLY_CONSUMED")):
            total += a["granted_bundles"] - a["consumed_bundles"]
    return total
