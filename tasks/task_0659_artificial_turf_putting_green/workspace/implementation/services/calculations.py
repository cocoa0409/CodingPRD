"""Calculation rules (PRD 3.2-3.5, 3.10, 3.11 / SCAFFOLD §1.3).

All money is integer cents, round-half-up per line BEFORE summing (PRD 2.5).
"""

import math

from common import round_half_up_2dp, round_half_up_cents

# --- Constants (SCAFFOLD §1.3) ---------------------------------------------
MIN_JOB_CENTS = 150000  # $1,500 minimum job floor

VARIANT_PCT = {
    "STANDARD": 0.00,
    "PET": 0.12,
    "PLAYGROUND": 0.18,
    "PUTTING_GREEN": 0.25,
}

VOLUME_TIER2_SQFT = 2000
VOLUME_TIER2_PCT = 0.10
VOLUME_TIER1_SQFT = 1000
VOLUME_TIER1_PCT = 0.05

EXCAVATION_CENTS_PER_SQFT_INCH = 22
FRENCH_DRAIN_CENTS_PER_SQFT = 180
PANEL_CENTS_PER_SQFT = 320

SLOPE_FLAT_MAX = 2.0
SLOPE_STEEP_MIN = 5.0

DEPOSIT_MIN_PCT = 0.10
DEPOSIT_MAX_PCT = 0.50

WARRANTY_COVERAGE_MONTHS = {"BASIC": 12, "PLUS": 36, "PREMIUM": 96}
WARRANTY_VISITS_PER_YEAR = {"BASIC": 0, "PLUS": 1, "PREMIUM": 2}

CALLBACK_FLAT_CENTS = 12500
REWORK_CENTS_PER_SQFT = 35

QUOTE_TTL_DAYS = 30


# --------------------------------------------------------------------------
# waste_factor (PRD 3.2)
# --------------------------------------------------------------------------
def compute_waste_factor_pct(longest_run_ft, roll_width_ft):
    """Number of roll runs = ceil(longest_run_ft / roll_width_ft); waste tier."""
    runs = math.ceil(longest_run_ft / roll_width_ft)
    if runs <= 1:
        return 5.0
    elif runs == 2:
        return 8.0
    elif runs <= 4:
        return 12.0
    else:
        return 15.0


def compute_net_area_sqft(gross_area_sqft, obstruction_area_sqft, waste_factor_pct):
    """(gross - obstruction) * (1 + waste/100), round half-up to 2 decimals."""
    raw = (gross_area_sqft - obstruction_area_sqft) * (1 + waste_factor_pct / 100.0)
    return round_half_up_2dp(raw)


# --------------------------------------------------------------------------
# drainage_tier (PRD 3.4) — three inputs, non-linear interaction.
# --------------------------------------------------------------------------
def compute_drainage_tier(slope_pct, soil_drains_freely, variant):
    if variant == "PUTTING_GREEN":
        return "DRAINAGE_PANEL"
    if (not soil_drains_freely) and slope_pct < SLOPE_FLAT_MAX:
        return "DRAINAGE_PANEL"
    if slope_pct >= SLOPE_STEEP_MIN or (not soil_drains_freely):
        return "FRENCH_DRAIN"
    return "NONE"


# --------------------------------------------------------------------------
# base_prep_cost (PRD 3.4)
# --------------------------------------------------------------------------
def compute_base_prep_costs(net_area_sqft, base_depth_in, drainage_tier):
    excavation = round_half_up_cents(
        net_area_sqft * base_depth_in * EXCAVATION_CENTS_PER_SQFT_INCH
    )
    if drainage_tier == "NONE":
        drainage = 0
    elif drainage_tier == "FRENCH_DRAIN":
        drainage = round_half_up_cents(net_area_sqft * FRENCH_DRAIN_CENTS_PER_SQFT)
    else:  # DRAINAGE_PANEL
        drainage = round_half_up_cents(net_area_sqft * PANEL_CENTS_PER_SQFT)
    return excavation, drainage


# --------------------------------------------------------------------------
# quote_total (PRD 3.5) — pinned order; round per line BEFORE summing.
# --------------------------------------------------------------------------
def compute_quote_pricing(
    net_area_sqft,
    variant,
    turf_price_per_sqft_cents,
    infill_price_per_sqft_cents,
    excavation_cost_cents,
    drainage_cost_cents,
    promo_code,
):
    """Returns a dict with all quote money components."""
    turf_line = round_half_up_cents(net_area_sqft * turf_price_per_sqft_cents)
    infill_line = round_half_up_cents(net_area_sqft * infill_price_per_sqft_cents)
    material_subtotal = turf_line + infill_line

    base_prep_subtotal = excavation_cost_cents + drainage_cost_cents

    variant_pct = VARIANT_PCT[variant]
    variant_surcharge = round_half_up_cents(material_subtotal * variant_pct)

    pre_discount = material_subtotal + base_prep_subtotal + variant_surcharge

    # Volume discount keyed on the design's net area tier.
    if net_area_sqft >= VOLUME_TIER2_SQFT:
        volume_pct = VOLUME_TIER2_PCT
    elif net_area_sqft >= VOLUME_TIER1_SQFT:
        volume_pct = VOLUME_TIER1_PCT
    else:
        volume_pct = 0.00
    volume_discount = round_half_up_cents(pre_discount * volume_pct)

    # Promo discount keyed on the code.
    if promo_code == "SPRING50":
        promo_discount = round_half_up_cents(pre_discount * 0.05)
    elif promo_code == "FLAT20000":
        promo_discount = 20000
    else:
        promo_discount = 0

    discount = volume_discount + promo_discount

    subtotal = pre_discount - discount
    total = max(subtotal, MIN_JOB_CENTS)

    return {
        "material_subtotal_cents": material_subtotal,
        "base_prep_subtotal_cents": base_prep_subtotal,
        "variant_surcharge_cents": variant_surcharge,
        "discount_cents": discount,
        "subtotal_cents": subtotal,
        "total_cents": total,
    }


# --------------------------------------------------------------------------
# deposit_amount (PRD 3.5) — clamp deposit_pct, then round.
# --------------------------------------------------------------------------
def compute_deposit_amount(total_cents, deposit_pct):
    clamped = min(DEPOSIT_MAX_PCT, max(DEPOSIT_MIN_PCT, deposit_pct))
    return round_half_up_cents(total_cents * clamped)


# --------------------------------------------------------------------------
# warranty_terms (PRD 3.10)
# --------------------------------------------------------------------------
def compute_warranty_terms(tier):
    return WARRANTY_COVERAGE_MONTHS[tier], WARRANTY_VISITS_PER_YEAR[tier]


# --------------------------------------------------------------------------
# callback_billing (PRD 3.11)
# --------------------------------------------------------------------------
COVERED_REASONS = {"SEAM_LIFT", "WRINKLE", "DRAINAGE"}
PET_REASONS = {"PET_ODOR", "INFILL_MIGRATION"}


def compute_callback_billing(reason, warranty_plan, project_variant, billable_area_sqft, now):
    """Decide billable + charge_cents (PRD 3.11).

    Covered (not billable) only when the callback names a warranty plan whose
    status is ACTIVE, the clock is before expires_at, and the reason qualifies.
    """
    from common import parse_iso8601

    is_covered = False
    if warranty_plan is not None and warranty_plan.get("status") == "ACTIVE":
        expires = parse_iso8601(warranty_plan.get("expires_at"))
        if expires is not None and now < expires:
            if reason in COVERED_REASONS:
                is_covered = True
            elif (
                reason in PET_REASONS
                and project_variant == "PET"
                and warranty_plan.get("tier") in {"PLUS", "PREMIUM"}
            ):
                is_covered = True

    billable = not is_covered
    if billable:
        charge = CALLBACK_FLAT_CENTS + round_half_up_cents(
            billable_area_sqft * REWORK_CENTS_PER_SQFT
        )
    else:
        charge = 0
    return billable, charge
