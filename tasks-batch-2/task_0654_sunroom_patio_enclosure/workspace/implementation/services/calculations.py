"""Calculation rules (PRD §2.8, §3, scaffold §1.3).

All monetary values are integer cents. Rounding is round-half-up (away from
zero at the halfway point) via Decimal, never float round().
"""
from decimal import Decimal, ROUND_HALF_UP

# ---- constants (scaffold §1.3) ----
SQIN_PER_SQFT = 144

SNOW_THRESHOLD_PSF = 30          # engineering: strict > 30
WIND_THRESHOLD_MPH = 130         # engineering: >= 130

BASE_RATE_CENTS = {
    "SCREEN_ROOM": 4500,
    "THREE_SEASON": 9000,
    "FOUR_SEASON": 16000,
}
MATERIAL_MULT_MILLI = {
    "ALUMINUM": 1000,
    "VINYL": 1150,
    "THERMAL_BREAK_ALUMINUM": 1300,
}

SLAB_POUR_CENTS = 320150
ENGINEERING_STAMP_CENTS = 95075
HOA_FILING_CENTS = 25033

TAX_RATE_MILLI = 75              # 7.5% in thousandths

# financing
TIER_EXCELLENT_MIN = 760
TIER_GOOD_MIN = 700
TIER_FAIR_MIN = 650
APR_EXCELLENT_BPS = 599
APR_GOOD_BPS = 999
APR_FAIR_BPS = 1499
MIN_APPROVAL_SCORE = 650
MAX_PRINCIPAL_CENTS = 7500000

# manufacture lead time
MATERIAL_BASE_DAYS = {
    "ALUMINUM": 21,
    "VINYL": 28,
    "THERMAL_BREAK_ALUMINUM": 35,
}
LARGE_FOOTPRINT_SQFT = 200       # strict > 200 surcharges
LARGE_SURCHARGE_DAYS = 14
FOUR_SEASON_SURCHARGE_DAYS = 10

# permit / warranty
PERMIT_VALIDITY_DAYS = 180
MAX_RESUBMISSIONS = 3
SITE_REST_BUFFER_HOURS = 24
WARRANTY_YEARS = {
    "SCREEN_ROOM": 1,
    "THREE_SEASON": 5,
    "FOUR_SEASON": 10,
}


def _round_half_up(value, places=0):
    """Round a Decimal half-up to the given number of decimal places."""
    quant = Decimal(1).scaleb(-places)  # 10^-places
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def footprint_area(width_in, depth_in):
    """footprint_sqft = round_half_up((width_in*depth_in)/144, 2). PRD §3.1."""
    w = Decimal(str(width_in))
    d = Decimal(str(depth_in))
    raw = (w * d) / Decimal(SQIN_PER_SQFT)
    return float(_round_half_up(raw, 2))


def engineering_requirement(structure_type, ground_snow_load_psf, design_wind_speed_mph):
    """requires_engineering per PRD §3.1 / calc engineering_requirement.

    snow uses strict > 30; wind uses >= 130.
    """
    return (
        structure_type == "FOUR_SEASON"
        or float(ground_snow_load_psf) > SNOW_THRESHOLD_PSF
        or int(design_wind_speed_mph) >= WIND_THRESHOLD_MPH
    )


def quote_base_price(footprint_sqft, structure_type, material):
    """base_price_cents = round_half_up(footprint * rate * mult / 1000). PRD §3.2."""
    rate = Decimal(BASE_RATE_CENTS[structure_type])
    mult = Decimal(MATERIAL_MULT_MILLI[material])
    fp = Decimal(str(footprint_sqft))
    raw = (fp * rate * mult) / Decimal(1000)
    return int(_round_half_up(raw, 0))


def quote_addons_total(existing_slab, requires_engineering, requires_hoa):
    """Sum of conditional add-on line items. PRD §3.2."""
    addons = 0
    if not existing_slab:
        addons += SLAB_POUR_CENTS
    if requires_engineering:
        addons += ENGINEERING_STAMP_CENTS
    if requires_hoa:
        addons += HOA_FILING_CENTS
    return addons


def quote_tax(base_price_cents, addons_cents):
    """Sum-then-round tax on (base+addons). PRD §2.8, §3.2.

    Returns (tax_cents, total_cents).
    """
    taxable = Decimal(base_price_cents + addons_cents)
    raw = (taxable * Decimal(TAX_RATE_MILLI)) / Decimal(1000)
    tax_cents = int(_round_half_up(raw, 0))
    total_cents = base_price_cents + addons_cents + tax_cents
    return tax_cents, total_cents


def financing_apr_tier(credit_score):
    """apr_bps selected by credit-score tier (>= cutoffs). PRD §3.3.

    Returns None when not approvable (score < MIN_APPROVAL_SCORE).
    """
    if credit_score >= TIER_EXCELLENT_MIN:
        return APR_EXCELLENT_BPS
    if credit_score >= TIER_GOOD_MIN:
        return APR_GOOD_BPS
    if credit_score >= TIER_FAIR_MIN:
        return APR_FAIR_BPS
    return None


def financing_monthly_payment(amount_financed_cents, apr_bps, term_months):
    """Standard amortization. Order pinned: principal -> monthly rate -> payment.

    PRD §3.3. Single round_half_up on the final payment.
    """
    P = Decimal(amount_financed_cents)
    n = int(term_months)
    # monthly rate r = (apr_bps / 10000) / 12
    r = (Decimal(apr_bps) / Decimal(10000)) / Decimal(12)
    if r == 0:
        raw = P / Decimal(n)
    else:
        one_plus_r_n = (Decimal(1) + r) ** n
        factor = (r * one_plus_r_n) / (one_plus_r_n - Decimal(1))
        raw = P * factor
    return int(_round_half_up(raw, 0))


def manufacture_lead_time(material, footprint_sqft, structure_type):
    """lead_time_days by material/footprint/structure. PRD §3.5.

    large surcharge strict > 200.
    """
    days = MATERIAL_BASE_DAYS[material]
    if float(footprint_sqft) > LARGE_FOOTPRINT_SQFT:
        days += LARGE_SURCHARGE_DAYS
    if structure_type == "FOUR_SEASON":
        days += FOUR_SEASON_SURCHARGE_DAYS
    return days


def warranty_term(structure_type):
    """term_years by structure_type. PRD §3.7."""
    return WARRANTY_YEARS[structure_type]
