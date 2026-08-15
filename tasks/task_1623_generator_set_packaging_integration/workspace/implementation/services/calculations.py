"""Business calculations from PRD Section 3 and the scaffold's calculations table.

All monetary values are integer cents; Decimal + ROUND_HALF_UP is used for any
multiplication that could produce a fractional cent.  Energy is 1 decimal kWh,
power factor 4 decimals, required kVA 1 decimal.
"""

import math
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Constants (scaffold calculations.constants)
# ---------------------------------------------------------------------------
TANK_PRICE_PER_GALLON_CENTS = 150

TIER_12_THRESHOLD_CENTS = 100_000_000
TIER_8_THRESHOLD_CENTS = 50_000_000

LOAD_BANK_RATE_CENTS_PER_KWH = 32
PF_PASS_THRESHOLD = 0.80

FLAT_RATE_CENTS_PER_KW_YEAR = 1200
PM_VISIT_HOURS = 6
LABOR_RATE_CENTS_PER_HOUR = 15000
PM_PARTS_ALLOWANCE_CENTS = 40000
PM_VISITS_PER_YEAR = 4
RISK_FACTOR = Decimal("1.15")

RESTOCKING_RATE = Decimal("0.10")

# Permit fee schedule
PERMIT_FEE_CA_CENTS = 250000
PERMIT_FEE_DE_CENTS = 175000
PERMIT_FEE_DEFAULT_CENTS = 100000
EXPIRY_DAYS_CA = 60
EXPIRY_DAYS_DE = 90
EXPIRY_DAYS_DEFAULT = 45

# Emissions tier ranks
TIER_RANK = {
    "TIER_2": 1,
    "EPA_TIER_4": 2,
    "STAGE_V": 3,
    "TIER_4_FINAL_CARB": 4,
}

# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------

def _dec(value):
    """Coerce a numeric value to Decimal safely (via str for floats)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_int(value):
    """Round a numeric to the nearest integer, half-up."""
    return int(_dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round to 1 decimal place, half-up; returns float."""
    return float(_dec(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to 2 decimal places, half-up; returns float."""
    return float(_dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value):
    """Round to 4 decimal places, half-up; returns float."""
    return float(_dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# sizing_required_kva (scaffold calculation)
# ---------------------------------------------------------------------------

def compute_required_kva(load_steps, largest_motor_kva, starting_method,
                         altitude_m, ambient_c, method):
    """Return required_kva (float, 1 decimal) per the selected variant."""
    running_kva = sum(
        _dec(step["kva"]) for step in load_steps if step.get("duty") == "CONTINUOUS"
    )
    largest = _dec(largest_motor_kva)
    multiplier = Decimal("3.0") if starting_method == "DOL" else Decimal("1.6")
    starting_kva = running_kva - largest + largest * multiplier
    base_kva = max(running_kva, starting_kva)

    if method == "NAMEPLATE_SUM":
        return round_half_up_1dp(base_kva)

    # DERATED_STOCHASTIC
    altitude_derate = Decimal("0.01") * max(0, math.floor((altitude_m - 1000) / 500))
    ambient_derate = Decimal("0.02") * max(0, math.floor((ambient_c - 40) / 5))
    derate_factor = Decimal("1") - altitude_derate - ambient_derate
    if derate_factor < Decimal("0.70"):
        derate_factor = Decimal("0.70")
    result = base_kva / derate_factor * Decimal("1.10")
    return round_half_up_1dp(result)


# ---------------------------------------------------------------------------
# fuel_tank_runtime (scaffold calculation)
# ---------------------------------------------------------------------------

def compute_fuel_config(order, engine_fuel_burn_gph, fuel_tank_gallons):
    """Return (usable_gallons, tank_price_cents, runtime_hours, min_runtime_hours)."""
    ullage = Decimal("0.12") if order["site_locale"] == "US_CA" else Decimal("0.10")
    usable = _dec(fuel_tank_gallons) * (Decimal("1") - ullage)
    usable_gallons = float(usable)

    tank_price_cents = fuel_tank_gallons * TANK_PRICE_PER_GALLON_CENTS

    runtime_hours = round_half_up_2dp(usable / _dec(engine_fuel_burn_gph))

    min_runtime = 48 if order["occupancy_type"] == "HOSPITAL" else 24
    return usable_gallons, tank_price_cents, runtime_hours, min_runtime


# ---------------------------------------------------------------------------
# order_total_price (scaffold calculation)
# ---------------------------------------------------------------------------

def compute_order_total(engine_list_price, alternator_list_price,
                        enclosure_price_cents, tank_price_cents,
                        freight_charge_cents):
    """Return (total_price_cents, discount_tier)."""
    equipment_subtotal = engine_list_price + alternator_list_price
    options_subtotal = enclosure_price_cents + tank_price_cents
    pre_discount = equipment_subtotal + options_subtotal

    if pre_discount >= TIER_12_THRESHOLD_CENTS:
        discount_tier = "TIER_12"
        rate = Decimal("0.12")
    elif pre_discount >= TIER_8_THRESHOLD_CENTS:
        discount_tier = "TIER_8"
        rate = Decimal("0.08")
    else:
        discount_tier = "NONE"
        rate = Decimal("0.0")

    discount_cents = round_half_up_int(_dec(pre_discount) * rate)
    total_price_cents = pre_discount - discount_cents + freight_charge_cents
    return total_price_cents, discount_tier


# ---------------------------------------------------------------------------
# load_bank_billing + test_verdict (scaffold calculations)
# ---------------------------------------------------------------------------

def compute_test_results(readings):
    """Return (total_kwh, measured_avg_pf, invoice_total_cents, verdict)."""
    total_kwh = Decimal("0")
    invoice_total_cents = 0
    weighted_pf_sum = Decimal("0")
    total_hours = Decimal("0")

    for step in readings:
        kw = _dec(step["kw"])
        hours = _dec(step["hours"])
        pf = _dec(step["power_factor"])

        step_kwh_raw = kw * hours
        step_kwh = _dec(round_half_up_1dp(step_kwh_raw))
        total_kwh += step_kwh

        step_charge = round_half_up_int(step_kwh * LOAD_BANK_RATE_CENTS_PER_KWH)
        invoice_total_cents += step_charge

        weighted_pf_sum += pf * hours
        total_hours += hours

    total_kwh = round_half_up_1dp(total_kwh)
    measured_avg_pf = round_half_up_4dp(weighted_pf_sum / total_hours)
    verdict = "PASS" if all(
        _dec(step["power_factor"]) >= _dec(PF_PASS_THRESHOLD) for step in readings
    ) else "FAIL"

    return total_kwh, measured_avg_pf, invoice_total_cents, verdict


# ---------------------------------------------------------------------------
# emissions_tier_determination (scaffold calculation)
# ---------------------------------------------------------------------------

def required_tier_for_locale(site_locale):
    if site_locale == "US_CA":
        return "TIER_4_FINAL_CARB"
    if site_locale == "DE":
        return "STAGE_V"
    return "EPA_TIER_4"


# ---------------------------------------------------------------------------
# service_contract_price (scaffold calculation)
# ---------------------------------------------------------------------------

def compute_contract_prices(pricing_variant, nameplate_kw, term_years, site_locale):
    """Return (annual_price_cents, total_price_cents)."""
    if pricing_variant == "FLAT_RISK_PREMIUM":
        if site_locale == "US_CA":
            locale_mult = Decimal("1.25")
        elif site_locale == "DE":
            locale_mult = Decimal("1.10")
        else:
            locale_mult = Decimal("1.0")
        annual = round_half_up_int(
            _dec(FLAT_RATE_CENTS_PER_KW_YEAR) * _dec(nameplate_kw) * locale_mult
        )
    else:  # TIME_AND_MATERIALS_EV
        per_visit = PM_VISIT_HOURS * LABOR_RATE_CENTS_PER_HOUR + PM_PARTS_ALLOWANCE_CENTS
        annual = round_half_up_int(
            _dec(per_visit) * PM_VISITS_PER_YEAR * RISK_FACTOR
        )
    total = annual * term_years
    return annual, total


# ---------------------------------------------------------------------------
# permit_fee_schedule (scaffold calculation)
# ---------------------------------------------------------------------------

def permit_fees_for_locale(locale):
    """Return (base_fee_cents, resubmission_fee_cents)."""
    if locale == "US_CA":
        base = PERMIT_FEE_CA_CENTS
    elif locale == "DE":
        base = PERMIT_FEE_DE_CENTS
    else:
        base = PERMIT_FEE_DEFAULT_CENTS
    resubmission = round_half_up_int(_dec(base) * Decimal("0.50"))
    return base, resubmission


def expiry_days_for_locale(locale):
    if locale == "US_CA":
        return EXPIRY_DAYS_CA
    if locale == "DE":
        return EXPIRY_DAYS_DE
    return EXPIRY_DAYS_DEFAULT


# ---------------------------------------------------------------------------
# restocking_refund (scaffold calculation)
# ---------------------------------------------------------------------------

def compute_restocking_refund(build_status_at_cancel, committed_amount_cents):
    """Return (restocking_fee_cents, refunded_amount_cents)."""
    if build_status_at_cancel in ("SPEC", "SIZING"):
        fee = 0
    else:
        fee = round_half_up_int(_dec(committed_amount_cents) * RESTOCKING_RATE)
    refund = committed_amount_cents - fee
    return fee, refund
