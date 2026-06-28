"""Calculation rules from SCAFFOLD.yaml §1.3 / PRD §3.

All monetary math uses Decimal with ROUND_HALF_UP at each rounding step in the
pinned evaluation order (PRD §2.9). Amounts are stored as integer cents.
"""
from decimal import Decimal, ROUND_HALF_UP

# ---- quote_pricing constants (SCAFFOLD §1.3 / PRD §3.4) ----
FOOTPRINT_TIER_1_MAX = 800
FOOTPRINT_TIER_1_BASE_CENTS = 250000
FOOTPRINT_TIER_2_MAX = 1500
FOOTPRINT_TIER_2_BASE_CENTS = 400000
FOOTPRINT_TIER_3_BASE_CENTS = 600000
VAPOR_RATE_CENTS_PER_SQFT = 180
SUMP_CENTS = 120000
DEHU_CENTS = 165000
BACKUP_CENTS = 90000
DRAIN_FREE_FT = 20
DRAIN_CENTS_PER_FT = 4500
TAX_RATE = Decimal("0.07")

# ---- assessment_severity constants (SCAFFOLD §1.3 / PRD §3.2) ----
MOISTURE_MID = 60.0
MOISTURE_HIGH = 80.0
STRUCT_CAP = 4
STRUCT_WEIGHT = 2
MODERATE_THRESHOLD = 4
SEVERE_THRESHOLD = 7

# ---- financing_amortization constants (SCAFFOLD §1.3 / PRD §3.6) ----
APR_TABLE = {
    "PRIME": {"SHORT": 599, "LONG": 799},
    "NEAR_PRIME": {"SHORT": 1099, "LONG": 1399},
    "SUBPRIME": {"SHORT": 1999, "LONG": 2399},
}
MAX_FINANCE_CENTS = {
    "PRIME": 5000000,
    "NEAR_PRIME": 3000000,
    "SUBPRIME": 1500000,
}

DISCOUNT_PCT = {
    "SPRING10": Decimal("0.10"),
    "SENIOR15": Decimal("0.15"),
}


def _round_half_up(value):
    """Round a Decimal to the nearest whole cent, half up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def footprint_tier_base(footprint_sqft):
    if footprint_sqft <= FOOTPRINT_TIER_1_MAX:
        return FOOTPRINT_TIER_1_BASE_CENTS
    if footprint_sqft <= FOOTPRINT_TIER_2_MAX:
        return FOOTPRINT_TIER_2_BASE_CENTS
    return FOOTPRINT_TIER_3_BASE_CENTS


def discount_pct_for(discount_code):
    return DISCOUNT_PCT.get(discount_code, Decimal("0.0"))


def price_scope(footprint_sqft, scope, drain_linear_ft, discount_code):
    """Run the pinned quote_pricing formula (PRD §3.4).

    scope: dict with includes_vapor_barrier/includes_sump/includes_dehumidifier/
    includes_battery_backup/includes_drain booleans.
    Returns dict: subtotal_cents, discount_cents, tax_cents, total_cents.

    Pinned order: line items -> subtotal -> discount -> tax -> total.
    """
    base_cents = footprint_tier_base(footprint_sqft)
    vapor_cents = VAPOR_RATE_CENTS_PER_SQFT * footprint_sqft if scope["includes_vapor_barrier"] else 0
    sump_cents = SUMP_CENTS if scope["includes_sump"] else 0
    dehu_cents = DEHU_CENTS if scope["includes_dehumidifier"] else 0
    backup_cents = BACKUP_CENTS if scope["includes_battery_backup"] else 0

    drain_billable_ft = max(0, drain_linear_ft - DRAIN_FREE_FT) if scope["includes_drain"] else 0
    drain_cents = drain_billable_ft * DRAIN_CENTS_PER_FT

    subtotal_cents = base_cents + vapor_cents + sump_cents + dehu_cents + backup_cents + drain_cents

    discount_pct = discount_pct_for(discount_code)
    discount_cents = _round_half_up(Decimal(subtotal_cents) * discount_pct)
    discounted = subtotal_cents - discount_cents

    tax_cents = _round_half_up(Decimal(discounted) * TAX_RATE)
    total_cents = discounted + tax_cents

    return {
        "subtotal_cents": subtotal_cents,
        "discount_cents": discount_cents,
        "tax_cents": tax_cents,
        "total_cents": total_cents,
    }


def reconcile_install(footprint_sqft, accepted_quote, actual_drain_linear_ft):
    """install_reconciliation (PRD §3.7).

    Re-run the quote_pricing formula on the accepted quote's frozen scope flags,
    substituting actual_drain_linear_ft for the quoted drain_linear_ft, using the
    accepted quote's discount percentage. Returns (final_total_cents, variance_cents).
    """
    scope = {
        "includes_vapor_barrier": accepted_quote["includes_vapor_barrier"],
        "includes_sump": accepted_quote["includes_sump"],
        "includes_dehumidifier": accepted_quote["includes_dehumidifier"],
        "includes_battery_backup": accepted_quote["includes_battery_backup"],
        "includes_drain": accepted_quote["includes_drain"],
    }
    priced = price_scope(
        footprint_sqft,
        scope,
        actual_drain_linear_ft,
        accepted_quote["discount_code"],
    )
    final_total_cents = priced["total_cents"]
    variance_cents = final_total_cents - accepted_quote["total_cents"]
    return final_total_cents, variance_cents


def compute_severity(moisture_pct, structural_findings_count, standing_water):
    """assessment_severity (PRD §3.2).

    Pinned order: score -> base threshold mapping -> standing-water override.
    standing_water is NOT a score input.
    """
    score = 0
    if moisture_pct >= MOISTURE_HIGH:
        score += 3
    elif moisture_pct >= MOISTURE_MID:
        score += 1
    score += min(structural_findings_count, STRUCT_CAP) * STRUCT_WEIGHT

    if score >= SEVERE_THRESHOLD:
        base = "SEVERE"
    elif score >= MODERATE_THRESHOLD:
        base = "MODERATE"
    elif score >= 1:
        base = "LOW"
    else:
        base = "NONE"

    severity = base
    if standing_water and structural_findings_count >= 1 and base in ("LOW", "NONE"):
        severity = "MODERATE"
    return severity


def term_bucket(term_months):
    return "SHORT" if term_months <= 24 else "LONG"


def compute_apr_bps(credit_band, term_months):
    return APR_TABLE[credit_band][term_bucket(term_months)]


def amortize(amount_financed_cents, apr_bps, term_months):
    """financing_amortization (PRD §3.6). Returns monthly_payment_cents (int).

    monthly rate r = apr_bps / 10000 / 12; if r == 0 payment = P/n, else
    standard amortization. Rounded half up to whole cents.
    """
    P = Decimal(amount_financed_cents)
    n = term_months
    r = Decimal(apr_bps) / Decimal(10000) / Decimal(12)
    if r == 0:
        payment = P / Decimal(n)
    else:
        one_plus_r_n = (Decimal(1) + r) ** n
        payment = P * r * one_plus_r_n / (one_plus_r_n - Decimal(1))
    return _round_half_up(payment)


def max_finance_cents(credit_band):
    return MAX_FINANCE_CENTS[credit_band]
