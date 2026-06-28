"""Calculation rules (SCAFFOLD §1.3). Decimal + round_half_up everywhere."""
from decimal import Decimal, ROUND_HALF_UP

# --- chemical_dose constants ---
BASE_OZ = {"ROOF_SOFT_WASH": 6, "HOUSE_WASH": 3, "CONCRETE_CLEAN": 4}
SOIL_MULT = {"LIGHT": "0.8", "MODERATE": "1.0", "HEAVY": "1.4"}
MIN_PRIME_OZ = Decimal("8.0")
MAX_TANK_OZ = Decimal("320.0")

# --- quote_line_total / visit_final_cost constants ---
SURFACE_RATE = {"ROOF": 22, "SIDING": 15, "CONCRETE": 11}  # cents per sqft
SERVICE_MULT = {"ROOF_SOFT_WASH": "1.25", "HOUSE_WASH": "1.0", "CONCRETE_CLEAN": "1.1"}
HEIGHT_STEP = Decimal("0.10")

# --- travel surcharge constants ---
LARGE_JOB_CENTS = 5000000
MID_JOB_CENTS = 1500000
FLAT_TRAVEL_CENTS = 7500

# --- weather ---
MAX_WIND = 35

# --- risk score constants ---
LOAD_RISK = 20
UNINSURED_RISK = 50
DECAY = Decimal("0.5")
RISK_CEILING = 100


def _round_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_1dp(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def chemical_dose_oz(measured_sqft, service_type, soiling_level):
    base = Decimal(BASE_OZ[service_type])
    tier = Decimal(SOIL_MULT[soiling_level])
    raw = (Decimal(measured_sqft) / Decimal(100)) * base * tier
    # Cap at tank max first, then raise to priming minimum.
    capped = min(raw, MAX_TANK_OZ)
    dosed = max(MIN_PRIME_OZ, capped)
    return _round_1dp(dosed)


def line_total_cents(measured_sqft, surface_type, service_type, stories):
    rate = Decimal(SURFACE_RATE[surface_type])
    svc = Decimal(SERVICE_MULT[service_type])
    story_mult = Decimal("1.0") + HEIGHT_STEP * (Decimal(stories) - Decimal(1))
    raw = Decimal(measured_sqft) * rate * svc * story_mult
    return _round_cents(raw)


def travel_surcharge_cents(subtotal_cents):
    if subtotal_cents >= LARGE_JOB_CENTS:
        raw = Decimal(0)
    elif subtotal_cents >= MID_JOB_CENTS:
        raw = Decimal(FLAT_TRAVEL_CENTS) / Decimal(2)
    else:
        raw = Decimal(FLAT_TRAVEL_CENTS)
    return _round_cents(raw)


def loyalty_pct(n):
    if n >= 10:
        return Decimal("0.15")
    if n >= 5:
        return Decimal("0.10")
    if n >= 2:
        return Decimal("0.05")
    return Decimal("0")


def loyalty_discount_cents(final_cost_cents, n):
    pct = loyalty_pct(n)
    return _round_cents(Decimal(final_cost_cents) * pct)
