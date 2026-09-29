"""Every calculation rule of PRD section 3, with the pinned rounding orders."""
from __future__ import annotations

from fractions import Fraction

import util

# --- device_risk_classification -------------------------------------------
FUNCTION_WEIGHT = 2
PHYSICAL_WEIGHT = 3
MAINTENANCE_WEIGHT = 1
NETWORK_ADDER = 4
AGE_ADDER_5Y = 1
AGE_ADDER_8Y = 3
RISK_CRITICAL_MIN = 34
RISK_HIGH_MIN = 26
RISK_MEDIUM_MIN = 16
PM_INTERVAL_DAYS = {"CRITICAL": 90, "HIGH": 180, "MEDIUM": 270, "LOW": 365}

# --- work_order_priority ---------------------------------------------------
SLA_HOURS = {"P1": 4, "P2": 24, "P3": 72}

# --- work_order_service_cost ----------------------------------------------
IN_HOUSE_LABOR_RATE_CENTS_PER_HOUR = 9000
AFTER_HOURS_MULTIPLIER = Fraction(3, 2)
DAY_SHIFT_START_HOUR = 7
DAY_SHIFT_END_HOUR = 19

# --- loaner_rental_cost ----------------------------------------------------
RENTAL_BASE_DAILY_CENTS = 24333
RENTAL_RISK_SURCHARGE_PCT = {
    "CRITICAL": Fraction(1, 4),
    "HIGH": Fraction(3, 20),
    "MEDIUM": Fraction(1, 20),
    "LOW": Fraction(0, 1),
}
RENTAL_LONG_TERM_DISCOUNT_PCT = Fraction(1, 10)
LONG_TERM_DISCOUNT_AFTER_DAY = 7

# --- department_downtime_debit --------------------------------------------
TIER_T0_PCT = 50
TIER_T1_PCT = 80
WARNING_PCT = 80
OVERHEAD_PCT = {"T0": Fraction(0, 1), "T1": Fraction(1, 20), "T2": Fraction(3, 25)}

# --- replacement_priority_score -------------------------------------------
W_AGE = Fraction(35, 100)
W_CONDITION = Fraction(30, 100)
W_BURDEN = Fraction(20, 100)
W_RISK = Fraction(15, 100)
RISK_WEIGHT = {
    "CRITICAL": Fraction(1, 1),
    "HIGH": Fraction(3, 4),
    "MEDIUM": Fraction(1, 2),
    "LOW": Fraction(1, 4),
}

# --- security_remediation_due ---------------------------------------------
REMEDIATION_SLA_DAYS = {"CRITICAL": 7, "HIGH": 30, "MEDIUM": 90, "LOW": 180}

# --- pm_compliance_rate ----------------------------------------------------
EMPTY_STRICT_VALUE = 0.00
EMPTY_OPERATIONAL_VALUE = 100.00


def age_years(acquisition_date_str, clock):
    acquired = util.parse_date(acquisition_date_str)
    age_days = (clock.date() - acquired).days
    if age_days >= 0:
        return age_days // 365
    # floor division keeps the "whole years" semantics for future-dated units
    return -((-age_days) // 365)


def device_risk_classification(device, model, clock):
    years = age_years(device["acquisition_date"], clock)
    network_adder = NETWORK_ADDER if model.get("is_network_connected") else 0
    if years >= 8:
        age_adder = AGE_ADDER_8Y
    elif years >= 5:
        age_adder = AGE_ADDER_5Y
    else:
        age_adder = 0
    risk_score = (
        device["function_code"] * FUNCTION_WEIGHT
        + device["physical_risk_code"] * PHYSICAL_WEIGHT
        + device["maintenance_requirement_code"] * MAINTENANCE_WEIGHT
        + network_adder
        + age_adder
    )
    if risk_score >= RISK_CRITICAL_MIN:
        risk_class = "CRITICAL"
    elif risk_score >= RISK_HIGH_MIN:
        risk_class = "HIGH"
    elif risk_score >= RISK_MEDIUM_MIN:
        risk_class = "MEDIUM"
    else:
        risk_class = "LOW"
    return risk_score, risk_class, PM_INTERVAL_DAYS[risk_class]


def replacement_priority_score(device, model, clock):
    years = age_years(device["acquisition_date"], clock)
    expected_life = model["expected_life_years"]
    age_factor = min(Fraction(1, 1), Fraction(years, expected_life))
    condition_factor = Fraction(device["condition_score"] - 1, 4)
    replacement_cost = model["replacement_cost_cents"]
    burden_factor = min(
        Fraction(1, 1), Fraction(device["lifetime_maintenance_cost_cents"], replacement_cost)
    )
    risk_weight = RISK_WEIGHT[device["risk_class"]]
    total = 100 * (
        W_AGE * age_factor
        + W_CONDITION * condition_factor
        + W_BURDEN * burden_factor
        + W_RISK * risk_weight
    )
    return util.two_dp(total)


def work_order_priority(reported_severity, risk_class):
    if reported_severity == "PATIENT_HARM" or risk_class == "CRITICAL":
        priority = "P1"
    elif reported_severity == "CLINICAL_IMPACT" or risk_class == "HIGH":
        priority = "P2"
    else:
        priority = "P3"
    return priority, SLA_HOURS[priority]


def shift_multiplier_for(started_at):
    hour = started_at.hour
    if hour < DAY_SHIFT_START_HOUR or hour >= DAY_SHIFT_END_HOUR:
        return AFTER_HOURS_MULTIPLIER
    return Fraction(1, 1)


def service_cost(labor_minutes, parts_cost_cents, service_mode, multiplier, vendor):
    """Provisional / list-rate cost. Numerator in full, THEN /60, THEN one rounding."""
    if service_mode == "VENDOR" and vendor is not None:
        rate = vendor["hourly_rate_cents"]
    else:
        rate = IN_HOUSE_LABOR_RATE_CENTS_PER_HOUR
    labor_cents = util.round_half_up_int(
        Fraction(labor_minutes) * rate * Fraction(multiplier) / 60
    )
    total = labor_cents + parts_cost_cents
    if service_mode == "VENDOR" and vendor is not None:
        total += vendor["travel_flat_cents"]
    return total


def loaner_billable_days(start_at, returned_at):
    elapsed = util.seconds_between(returned_at, start_at)
    if elapsed <= 0:
        return 1
    return max(1, util.ceil_div(elapsed, 86400))


def loaner_rental_cost(source, billable_days, downed_risk_class):
    if source == "POOL":
        return 0
    surcharge = RENTAL_RISK_SURCHARGE_PCT[downed_risk_class]
    total = 0
    for day in range(1, billable_days + 1):
        day_rate = Fraction(RENTAL_BASE_DAILY_CENTS) * (1 + surcharge)
        if day > LONG_TERM_DISCOUNT_AFTER_DAY:
            day_rate = day_rate * (1 - RENTAL_LONG_TERM_DISCOUNT_PCT)
        total += util.round_half_up_int(day_rate)
    return total


def overhead_tier(pre_spend_cents, budget_cents):
    if pre_spend_cents * 100 < budget_cents * TIER_T0_PCT:
        return "T0"
    if pre_spend_cents * 100 < budget_cents * TIER_T1_PCT:
        return "T1"
    return "T2"


def department_charge(final_cost_cents, pre_spend_cents, budget_cents, loaner_total_cents):
    tier = overhead_tier(pre_spend_cents, budget_cents)
    overhead = OVERHEAD_PCT[tier]
    scaled = util.round_half_up_int(Fraction(final_cost_cents) * (1 + overhead))
    return scaled + loaner_total_cents


def budget_state_for(spend_cents, budget_cents):
    if spend_cents >= budget_cents:
        return "ON_HOLD"
    if spend_cents * 100 >= budget_cents * WARNING_PCT:
        return "WARNING"
    return "OPEN"


def hours_2dp(seconds):
    return util.two_dp(Fraction(seconds, 3600))


def pct_2dp(numerator, denominator):
    return util.two_dp(Fraction(100 * numerator, denominator))
