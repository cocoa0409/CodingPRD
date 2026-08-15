"""Calculation rules (scaffold `calculations`, PRD 3.3/3.5/3.6/3.9).
All money is integer cents; rounding is round-half-up via Decimal. No floats
touch money."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

# order_line_pricing constants
TIER1_MIN_CENTS = 5_000_000
TIER1_RATE = Decimal("0.015")
TIER2_MIN_CENTS = 10_000_000
TIER2_RATE = Decimal("0.03")

# doc_fee constants
FEE_RATE = Decimal("0.01")
FEE_MIN_CENTS = 25_000
FEE_MAX_CENTS = 75_000

# transport_quote constants
PER_MILE_PER_SECTION_CENTS = 250
ESCORT_PER_MILE_CENTS = 150
MULTIWIDE_FLAT_CENTS = 150_000
FREE_MILES = 100
OVERAGE_PER_MILE_CENTS = 90
WEEKEND_FLAT_CENTS = 50_000

# loan_payment constants
CHATTEL_RATE_FLOOR_BPS = 700
CHATTEL_TERM_CAP_MONTHS = 240
REAL_PROPERTY_RATE_FLOOR_BPS = 450
REAL_PROPERTY_TERM_CAP_MONTHS = 360

# trade_in_credit constants
TRADE_IN_BASE = {"A": 1_800_000, "B": 1_200_000, "C": 600_000}
DEPRECIATION_PER_YEAR = Decimal("0.03")
DEPRECIATION_GRACE_YEARS = 10
TRADE_IN_FLOOR_CENTS = 200_000

# warranty_coverage_window constants
FACTORY_COVERAGE_DAYS = 365
INSTALL_COVERAGE_DAYS = 90

# delay_compensation constants
DELAY_GRACE_DAYS = 2
DELAY_PER_DIEM_CENTS = 7_500
DELAY_CAP_CENTS = 75_000


def rhu(x):
    """Round-half-up a Decimal to whole cents (integer)."""
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tier_rate(subtotal_cents):
    if subtotal_cents >= TIER2_MIN_CENTS:
        return TIER2_RATE
    if subtotal_cents >= TIER1_MIN_CENTS:
        return TIER1_RATE
    return Decimal("0")


def price_order(agreed_home_price_cents, active_option_line_totals):
    """calc order_line_pricing + doc_fee. Discount is computed PER LINE, each
    line rounded half-up to whole cents, then summed (pinned mode b). The fee
    base is (subtotal - discount), NOT the final total (pinned mode c)."""
    lines = [agreed_home_price_cents] + list(active_option_line_totals)
    subtotal = sum(lines)
    rate = tier_rate(subtotal)
    discount = sum(rhu(Decimal(line) * rate) for line in lines)
    options_total = sum(active_option_line_totals)
    discounted = subtotal - discount
    doc_fee = rhu(Decimal(discounted) * FEE_RATE)
    doc_fee = max(FEE_MIN_CENTS, min(FEE_MAX_CENTS, doc_fee))
    total = discounted + doc_fee
    return {
        "subtotal_cents": subtotal,
        "options_total_cents": options_total,
        "discount_cents": discount,
        "doc_fee_cents": doc_fee,
        "total_price_cents": total,
    }


def min_deposit_cents(total_price_cents):
    """round_half_up(5% * total_price_cents)."""
    return rhu(Decimal(total_price_cents) * Decimal("0.05"))


def annuity_payment_cents(principal_cents, apr_bps, term_months):
    """calc loan_payment: i = apr_bps/10000/12;
    payment = round_half_up(P * i / (1 - (1+i)^(-term)))."""
    i = Decimal(apr_bps) / Decimal(10000) / Decimal(12)
    denom = Decimal(1) - (Decimal(1) + i) ** (-term_months)
    return rhu(Decimal(principal_cents) * i / denom)


def rate_floor_bps(financing_type):
    return CHATTEL_RATE_FLOOR_BPS if financing_type == "CHATTEL" else REAL_PROPERTY_RATE_FLOOR_BPS


def term_cap_months(financing_type):
    return CHATTEL_TERM_CAP_MONTHS if financing_type == "CHATTEL" else REAL_PROPERTY_TERM_CAP_MONTHS


def escort_required_count(width_ft):
    """calc escort_requirement — boundary pinned: >= comparisons; exactly 14.0
    requires 1 escort; exactly 16.0 requires 2."""
    w = Decimal(str(width_ft))
    if w >= Decimal("16.0"):
        return 2
    if w >= Decimal("14.0"):
        return 1
    return 0


def transport_quote_cents(sections_count, distance_miles, escort_vehicle_count,
                          escort_required, scheduled_start_date):
    """calc transport_quote — sum of five exact integer-cent terms."""
    base = sections_count * distance_miles * PER_MILE_PER_SECTION_CENTS
    escort = (escort_vehicle_count * distance_miles * ESCORT_PER_MILE_CENTS
              if escort_required else 0)
    multiwide = MULTIWIDE_FLAT_CENTS if sections_count >= 2 else 0
    overage = max(0, distance_miles - FREE_MILES) * OVERAGE_PER_MILE_CENTS
    weekend = (WEEKEND_FLAT_CENTS
               if scheduled_start_date.weekday() in (5, 6) else 0)  # Sat=5, Sun=6
    return base + escort + multiwide + overage + weekend


def provisional_credit_cents(clock_year, declared_model_year, declared_condition):
    """calc trade_in_credit provisional variant."""
    base = TRADE_IN_BASE[declared_condition]
    age_years = max(0, clock_year - declared_model_year - DEPRECIATION_GRACE_YEARS)
    depreciated = rhu(Decimal(base) * (Decimal(1) - DEPRECIATION_PER_YEAR * age_years))
    return max(TRADE_IN_FLOOR_CENTS, depreciated)


def final_credit_cents(appraised_value_cents, reconditioning_cost_cents):
    """calc trade_in_credit final variant."""
    return max(0, appraised_value_cents - reconditioning_cost_cents)


def whole_delay_days(original_dt, new_dt):
    """floor of elapsed seconds / 86400."""
    return int((new_dt - original_dt).total_seconds() // 86400)


def delay_compensation_cents(delay_days):
    """calc delay_compensation — threshold at delay_days >= 3 (>=, not >)."""
    if delay_days < 3:
        return 0
    return min(DELAY_CAP_CENTS, (delay_days - DELAY_GRACE_DAYS) * DELAY_PER_DIEM_CENTS)


def window_dates(start_dt, sections_count):
    """Half-open move window [start, start + sections days) as date objects."""
    start = start_dt.date()
    return [start + timedelta(days=k) for k in range(sections_count)]


def lot_fits(model_section_count, model_length_ft, lot_max_sections, lot_max_length_ft):
    """calc lot_fit — <= semantics, equality allowed on both dimensions."""
    return (model_section_count <= lot_max_sections
            and Decimal(str(model_length_ft)) <= Decimal(str(lot_max_length_ft)))
