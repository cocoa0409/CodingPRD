"""Calculation rules (§1.3 / PRD §3). All money is whole cents, round_half_up."""
from decimal import Decimal, ROUND_HALF_UP

from timeutil import days_ceil, parse_dt

# ---- Constants ----
DAILY_RATE_BY_CLIMATE = {"AMBIENT": 500, "COOL": 800, "COLD": 1200}
SIZE_MULT = {"SMALL": Decimal("1.0"), "MEDIUM": Decimal("1.5"), "LARGE": Decimal("2.0")}

COVERAGE_MULT = {"STORAGE_ONLY": Decimal("1.0"), "TRANSIT": Decimal("1.5"), "ALL_RISK": Decimal("2.0")}
FRAGILITY_MULT = {"LOW": Decimal("1.0"), "MEDIUM": Decimal("1.25"), "HIGH": Decimal("1.5")}
MIN_PREMIUM_CENTS = 5000

CREW_HOURLY_CENTS = 9000
RIGGING_SURCHARGE_CENTS = 25000

TAX_RATE = Decimal("0.0875")

SETUP_BUFFER_MINUTES = 60


def round_half_up(value):
    """Round a Decimal to the nearest whole integer, halves up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- storage_fee (dual variant) ----
def storage_fee(climate_class, size_class, start_at_iso, end_iso):
    daily = DAILY_RATE_BY_CLIMATE[climate_class]
    size_mult = SIZE_MULT[size_class]
    days = days_ceil(parse_dt(start_at_iso), parse_dt(end_iso))
    return round_half_up(Decimal(days) * Decimal(daily) * size_mult)


# ---- appraisal_value (dual variant) ----
def appraisal_value(method, comparable_base_cents, replacement_multiplier, restoration_reserve_cents):
    if method == "FAIR_MARKET":
        return int(comparable_base_cents)
    # REPLACEMENT
    mult = Decimal(str(replacement_multiplier))
    scaled = round_half_up(Decimal(comparable_base_cents) * mult)
    return scaled + int(restoration_reserve_cents)


# ---- insurance_premium (tiered) ----
def insurance_premium(insured_value_cents, coverage_type, fragility_class, start_iso, end_iso):
    v = insured_value_cents
    if v <= 500000:
        rate_bps = 200
    elif v <= 5000000:
        rate_bps = 150
    else:
        rate_bps = 100
    coverage_mult = COVERAGE_MULT[coverage_type]
    fragility_mult = FRAGILITY_MULT[fragility_class]
    duration_days = Decimal((parse_dt(end_iso) - parse_dt(start_iso)).total_seconds()) / Decimal(86400)
    base_annual = Decimal(v) * Decimal(rate_bps) / Decimal(10000)
    scaled = base_annual * coverage_mult * fragility_mult * (duration_days / Decimal(365))
    premium = round_half_up(scaled)
    return max(MIN_PREMIUM_CENTS, premium)


# ---- transport_charge (dual variant) ----
def transport_charge(hours, requires_rigging):
    surcharge = RIGGING_SURCHARGE_CENTS if requires_rigging else 0
    labor = round_half_up(Decimal(str(hours)) * Decimal(CREW_HOURLY_CENTS))
    return labor + surcharge


# ---- invoice_total (aggregation, pinned rounding order) ----
def invoice_total(line_items):
    subtotal = sum(int(li["amount_cents"]) for li in line_items)
    tax = round_half_up(Decimal(subtotal) * TAX_RATE)
    total = subtotal + tax
    return subtotal, tax, total
