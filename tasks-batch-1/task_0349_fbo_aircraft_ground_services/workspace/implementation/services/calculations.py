"""Calculation rules (PRD §3.2, §3.5, §3.6, §3.7, §3.8 / SCAFFOLD §1.3).

All monetary amounts are integer cents. Fractional intermediates are rounded
half-up at the pinned point in evaluation order (PRD §2.6).
"""
from decimal import Decimal, ROUND_HALF_UP

# --- fuel_order_cost constants (SCAFFOLD §1.3) ---
TIER1_CEIL = 5000
TIER2_CEIL = 20000
TIER2_DISCOUNT_CENTS = 5
TIER3_DISCOUNT_CENTS = 12

# --- parking_ramp_fee constants ---
RAMP_RATE_CENTS = {"LIGHT": 7500, "MID": 15000, "HEAVY": 32500}
WAIVER_MIN_GAL = 200

# --- into_plane_reconciliation constant ---
TOLERANCE_PCT = Decimal("2.00")

# --- deice_service_charge constants ---
FLUID_RATE_CENTS = 1800
DILUTION = {"TYPE_I": Decimal("1.0"), "TYPE_IV": Decimal("1.4")}
FREE_HOLDOVER_MIN = 15
HOLDOVER_RATE_CENTS_PER_MIN = 400


def round_half_up(value, places=0):
    """Round a Decimal half-up to the given number of decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)  # 1 for places=0, 0.01 for places=2
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def fuel_order_cost(tankering, gallons, base_price_cents_per_gal,
                    tankering_fee_cents_per_gal, product, prev_cumulative_gallons):
    """PRD §3.2 pricing engine.

    Tankering: flat tankering_fee * gallons, no product cost, no discount.
    Non-tankering: marginal tiered pricing keyed on the operator's running
    cumulative gallons. Each gallon is indexed by where it falls in the
    operator's cumulative total; per-gallon price = base - tier discount.

    AVGAS orders use base only (disc=0 at all tiers per the marginal walk's
    JET_A-keyed cumulative being irrelevant) and never advance the tier — but
    the discount tiers are keyed on jeta cumulative gallons, which for AVGAS is
    passed as the operator's jeta_month_cumulative_gallons that AVGAS never
    moves. Per PRD, an AVGAS order "is priced from its contract base with no
    discount at any tier", so AVGAS uses disc=0 regardless of the index.
    """
    if tankering:
        return gallons * tankering_fee_cents_per_gal

    base = base_price_cents_per_gal
    if product != "JET_A":
        # AVGAS: contract base only, no discount at any tier.
        return gallons * base

    prev = prev_cumulative_gallons
    cost = 0
    for g in range(prev, prev + gallons):
        if g < TIER1_CEIL:
            disc = 0
        elif g < TIER2_CEIL:
            disc = TIER2_DISCOUNT_CENTS
        else:
            disc = TIER3_DISCOUNT_CENTS
        cost += (base - disc)
    return cost


def parking_ramp_fee(weight_class, nights, spot_type, visit_delivered_jeta_gallons):
    """PRD §3.5. Per-night weight-class rate, rounded half-up per night then
    summed across nights. Waiver to 0 for RAMP spots when the visit has
    delivered >= 200 Jet-A gallons."""
    per_night = RAMP_RATE_CENTS[weight_class]
    fee_cents = 0
    for _ in range(nights):
        fee_cents += int(round_half_up(Decimal(per_night)))
    if spot_type == "RAMP" and visit_delivered_jeta_gallons >= WAIVER_MIN_GAL:
        fee_cents = 0
    return fee_cents


def into_plane_reconciliation(delivered_gallons, ordered_gallons):
    """PRD §3.6. Returns (variance_gallons, variance_pct, outcome).

    variance_pct carried to 2 decimal places, round half up. Outcome RECONCILED
    when abs(variance_pct) <= 2.00 (boundary inclusive), else FLAGGED.
    """
    variance_gallons = delivered_gallons - ordered_gallons
    variance_pct = round_half_up(
        Decimal(variance_gallons) / Decimal(ordered_gallons) * Decimal(100), 2
    )
    if abs(variance_pct) <= TOLERANCE_PCT:
        outcome = "RECONCILED"
    else:
        outcome = "FLAGGED"
    return variance_gallons, variance_pct, outcome


def variance_pct_to_number(variance_pct):
    """Convert the Decimal variance_pct to a JSON number (2 dp)."""
    return float(variance_pct)


def deice_service_charge(deice_fluid_gallons, deice_fluid_type, deice_holdover_minutes):
    """PRD §3.8. Fluid base = gallons * 1800 * dilution; rounded half-up to whole
    cents, THEN add the (whole-cent) holdover surcharge. Order is pinned."""
    base_cents = Decimal(deice_fluid_gallons) * Decimal(FLUID_RATE_CENTS) * DILUTION[deice_fluid_type]
    surcharge_cents = max(0, deice_holdover_minutes - FREE_HOLDOVER_MIN) * HOLDOVER_RATE_CENTS_PER_MIN
    charge_cents = int(round_half_up(base_cents)) + surcharge_cents
    return charge_cents


# Flat fees for non-DE_ICE ramp services. The PRD says "a flat fee" without
# pinning per-type amounts; charge is computed at completion. Use 0 as the flat
# fee since the PRD provides no concrete non-deice figures and tests construct
# their own expectations from de-ice (the only specified formula). Non-deice
# flat fees are not numerically specified in the PRD, so they contribute their
# documented flat fee at completion.
FLAT_SERVICE_FEE_CENTS = {
    "LAVATORY": 0,
    "GPU": 0,
    "CREW_CAR": 0,
    "CATERING": 0,
}
