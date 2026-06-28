"""Calculation rules (§1.3 / PRD §3). All money in integer cents, round_half_up.

Never use float for money rounding — use Decimal with ROUND_HALF_UP.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- Constants (PRD §3.3, §3.4, §3.7, §3.8, §3.12) ----

SCOPE_BALLPARK_RATE_CENTS = {"PAINT": 12000, "REFACE": 28000, "REDOOR": 45000}

SCOPE_FOOT_RATE_CENTS = {"PAINT": 9000, "REFACE": 20000, "REDOOR": 30000}
SCOPE_DOOR_RATE_CENTS = {"PAINT": 1500, "REFACE": 4000, "REDOOR": 7000}
FINISH_MULTIPLIER = {
    "PAINT": Decimal("1.00"),
    "LAMINATE": Decimal("1.10"),
    "THERMOFOIL": Decimal("1.15"),
    "WOOD_VENEER": Decimal("1.25"),
    "SOLID_WOOD": Decimal("1.40"),
}

CO_LEAD_PER_FOOT_DAYS = 2
CO_LEAD_DOOR_FLAT_DAYS = 3
RUSH_FACTOR = Decimal("0.5")

FINISH_LEAD_DAYS = {
    "PAINT": 7, "LAMINATE": 14, "THERMOFOIL": 21, "WOOD_VENEER": 28, "SOLID_WOOD": 42,
}
SCOPE_LEAD_ADD_DAYS = {"PAINT": 0, "REFACE": 5, "REDOOR": 10}
VOLUME_LEAD_STEP_DAYS = 7
LARGE_JOB_FEET = 30

APR_BY_TERM = {
    12: Decimal("0.0399"),
    24: Decimal("0.0599"),
    36: Decimal("0.0799"),
    48: Decimal("0.0999"),
    60: Decimal("0.1199"),
}
DTI_MAX = Decimal("0.20")

QUOTE_VALID_DAYS = 30
WARRANTY_DAYS = 90


def round_half_up_cents(value):
    """Round a Decimal to integer cents using round-half-up (away from zero)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _d(x):
    """Make a Decimal that exactly represents the given numeric value."""
    return Decimal(str(x))


# ---- provisional_estimate (variant A) — PRD §3.3 ----
def provisional_estimate(scope, linear_feet):
    rate = SCOPE_BALLPARK_RATE_CENTS[scope]
    return round_half_up_cents(_d(rate) * _d(linear_feet))


# ---- firm_quote_total (variant B) — PRD §3.4 ----
def firm_quote_total(scope, linear_feet, door_count, finish_code, addons_total_cents):
    foot_rate = SCOPE_FOOT_RATE_CENTS[scope]
    door_rate = SCOPE_DOOR_RATE_CENTS[scope]
    labor_base = _d(foot_rate) * _d(linear_feet)            # step 1
    door_labor = _d(door_rate) * _d(door_count)             # step 2
    pre_finish = labor_base + door_labor                    # step 3
    finish_mult = FINISH_MULTIPLIER[finish_code]            # step 4
    materials = round_half_up_cents(pre_finish * (finish_mult - Decimal("1.0")))  # step 5
    subtotal = round_half_up_cents(pre_finish) + materials  # step 6
    # step 7: tiered volume discount by subtotal
    if subtotal < 1500000:
        vol_pct = Decimal("0.00")
    elif subtotal < 3000000:
        vol_pct = Decimal("0.05")
    else:
        vol_pct = Decimal("0.10")
    discount = round_half_up_cents(_d(subtotal) * vol_pct)  # step 8
    firm_total = subtotal - discount + int(addons_total_cents)  # step 9
    return firm_total


# ---- change_order_delta — PRD §3.7 ----
def change_order_delta(scope, finish_code, delta_linear_feet, delta_door_count, rush):
    foot_rate = SCOPE_FOOT_RATE_CENTS[scope]
    door_rate = SCOPE_DOOR_RATE_CENTS[scope]
    foot_delta = _d(foot_rate) * _d(delta_linear_feet)
    door_delta = _d(door_rate) * _d(delta_door_count)
    raw_delta = foot_delta + door_delta
    finish_mult = FINISH_MULTIPLIER[finish_code]
    price_delta_cents = round_half_up_cents(raw_delta * finish_mult)

    foot_lead = math.ceil(max(float(delta_linear_feet), 0.0)) * CO_LEAD_PER_FOOT_DAYS
    door_lead = CO_LEAD_DOOR_FLAT_DAYS if delta_door_count > 0 else 0
    base_lead = foot_lead + door_lead
    if rush:
        lead_time_delta_days = math.ceil(float(_d(base_lead) * RUSH_FACTOR))
    else:
        lead_time_delta_days = base_lead
    if lead_time_delta_days < 0:
        lead_time_delta_days = 0
    return price_delta_cents, int(lead_time_delta_days)


# ---- base_lead_time — PRD §3.8 ----
def base_lead_time_days(finish_code, scope, linear_feet):
    base = FINISH_LEAD_DAYS[finish_code]
    scope_add = SCOPE_LEAD_ADD_DAYS[scope]
    volume_add = VOLUME_LEAD_STEP_DAYS if _d(linear_feet) >= LARGE_JOB_FEET else 0
    return base + scope_add + volume_add


# ---- financing_monthly_payment — PRD §3.12 ----
def financing_monthly_payment(amount_cents, term_months, annual_income_cents):
    apr = APR_BY_TERM[term_months]
    r = apr / Decimal(12)
    n = term_months
    if r == 0:
        monthly_payment_cents = round_half_up_cents(_d(amount_cents) / Decimal(n))
    else:
        one_plus_r_n = (Decimal(1) + r) ** n
        factor = (r * one_plus_r_n) / (one_plus_r_n - Decimal(1))
        monthly_payment_cents = round_half_up_cents(_d(amount_cents) * factor)

    if int(annual_income_cents) == 0:
        # Guard against division by zero; treated as a very high (out-of-range) DTI.
        # PRD does not specify zero-income behavior; keep it explicit and finite.
        dti = Decimal(0) if monthly_payment_cents == 0 else Decimal("999999.0000")
    else:
        dti = (_d(monthly_payment_cents) * Decimal(12)) / _d(annual_income_cents)
    dti_ratio = dti.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return monthly_payment_cents, float(dti_ratio)
