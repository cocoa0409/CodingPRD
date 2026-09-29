"""The seven calculation rules. Decimal only -- never binary floats for money."""
from common import (ALARM_THRESHOLD, BALANCE_TOLERANCE_PSI, BAND_COLD_MAX_F,
                    BAND_MILD_MAX_F, BUCKET_ORDER, CO2_BASE_VOLUMES, CO2_PCT_CEILING,
                    CO2_PCT_FLOOR, D, FAUCET_LOSS_PSI, FLUSH_FACTOR,
                    FOAM_ALLOWANCE_LITERS_PER_DAY, FUNDED_SCOPE_BUCKETS,
                    GLYCOL_PENALTY_PER_PCT, GLYCOL_SERVICE_INTERVAL_DAYS,
                    MAX_DAYS_AT_RISK, MIN_EFFECTIVE_PCT, MIN_GLYCOL_PCT, MIN_PUMP_PSI,
                    MIN_SOLUTION_LITERS, MIN_TEMP_F, NITRO_REQUIRED_CO2_PCT,
                    NITRO_TARGET_VOLUMES, PUMP_PENALTY_FLAT, READING_WINDOW,
                    RESTRICTION_PSI_PER_FOOT, RISE_PSI_PER_FOOT, SERVICE_PENALTY_PER_DAY,
                    SEVERITY_FACTOR, TARGET_ACTIVE_PCT, TARGET_CO2_VOLUMES,
                    TARGET_COOLER_TEMP_F, TEMP_PENALTY_PER_DEGREE, TEMP_PSI_SLOPE,
                    TEMP_REF_F, VOLUME_L_PER_FOOT, VOL_TO_PSI, WATCH_THRESHOLD,
                    WAIVER_WITHHOLD_BPS, WHOLESALE_CENTS_PER_LITER, ceil_int, floor_int,
                    rhu, rhu_int, whole_days_between)


# ------------------------------------------------ 1. chemical_cycle_dosing (PRD 3.4)

def dosing(line, lot, chemical_type, contact_minutes, recirculation_temp_f,
           concentrate_liters_used):
    bore = D(line["inner_diameter_inches"])
    line_volume_liters = rhu(D(line["run_length_feet"]) * VOLUME_L_PER_FOOT[bore], 3)
    total_solution_liters = max(MIN_SOLUTION_LITERS,
                               ceil_int(line_volume_liters * FLUSH_FACTOR))
    stock = D(lot["concentration_pct_stock"])
    prescribed_concentrate_liters = rhu(
        D(total_solution_liters) * TARGET_ACTIVE_PCT[chemical_type] / stock, 2)
    effective_active_pct = rhu(
        D(concentrate_liters_used) * stock / D(total_solution_liters), 3)
    required_contact_minutes = contact_tier(chemical_type, effective_active_pct)
    temp = D(recirculation_temp_f)
    if temp < MIN_TEMP_F[chemical_type]:
        result = "FAIL_TEMPERATURE"
    elif effective_active_pct < MIN_EFFECTIVE_PCT[chemical_type]:
        result = "FAIL_CONCENTRATION"
    elif D(contact_minutes) < D(required_contact_minutes):
        result = "FAIL_CONTACT_TIME"
    else:
        result = "PASS"
    return {
        "line_volume_liters": line_volume_liters,
        "total_solution_liters": total_solution_liters,
        "prescribed_concentrate_liters": prescribed_concentrate_liters,
        "effective_active_pct": effective_active_pct,
        "required_contact_minutes": required_contact_minutes,
        "compliance_result": result,
    }


def contact_tier(chemical_type, effective_active_pct):
    """Tiers read off the already-rounded effective_active_pct."""
    pct = D(effective_active_pct)
    if chemical_type == "CAUSTIC":
        if pct >= D("2.0"):
            return 15
        if pct >= D("1.5"):
            return 20
        return 30
    if pct >= D("1.0"):
        return 10
    if pct >= D("0.75"):
        return 15
    return 25


# --------------------------------------------------- 2. gas_balance_target (PRD 3.5)

def gas_balance(line, measured_temp_f):
    temp = D(measured_temp_f)
    style = line["beer_style_group"]
    if style == "NITRO":
        target = NITRO_TARGET_VOLUMES
    else:
        if temp <= BAND_COLD_MAX_F:
            band = "COLD"
        elif temp <= BAND_MILD_MAX_F:
            band = "MILD"
        else:
            band = "WARM"
        target = TARGET_CO2_VOLUMES[style][band]
    equilibrium_psi = rhu((target - CO2_BASE_VOLUMES) * VOL_TO_PSI
                          + (temp - TEMP_REF_F) * TEMP_PSI_SLOPE, 2)
    bore = D(line["inner_diameter_inches"])
    total_restriction_psi = rhu(
        D(line["run_length_feet"]) * RESTRICTION_PSI_PER_FOOT[bore]
        + D(line["vertical_rise_feet"]) * RISE_PSI_PER_FOOT + FAUCET_LOSS_PSI, 2)
    required_applied_psi = rhu(max(equilibrium_psi, total_restriction_psi), 2)
    if style == "NITRO":
        required_co2_pct = NITRO_REQUIRED_CO2_PCT
    else:
        raw = rhu(equilibrium_psi / required_applied_psi * D(100), 1)
        required_co2_pct = min(CO2_PCT_CEILING, max(CO2_PCT_FLOOR, raw))
    gap = total_restriction_psi - equilibrium_psi
    if abs(gap) <= BALANCE_TOLERANCE_PSI:
        balance_state = "BALANCED"
    elif total_restriction_psi > equilibrium_psi:
        balance_state = "RESTRICTION_HIGH"
    else:
        balance_state = "PRESSURE_HIGH"
    return {
        "target_co2_volumes": target,
        "equilibrium_psi": equilibrium_psi,
        "total_restriction_psi": total_restriction_psi,
        "required_applied_psi": required_applied_psi,
        "required_co2_pct": required_co2_pct,
        "balance_state": balance_state,
    }


# ---------------------------------------------- 3. visit_charge_settlement (PRD 3.7)

def per_line_amount_cents(per_line_rate_cents, frequency_multiplier):
    """The per-line amount is rounded once, before any multiplication by line count."""
    return rhu_int(D(per_line_rate_cents) * D(frequency_multiplier))


def visit_charge(per_line_rate_cents, frequency_multiplier, visit_base_fee_cents,
                 billable_line_count, parts_charge_cents, apply_withhold):
    per_line = per_line_amount_cents(per_line_rate_cents, frequency_multiplier)
    gross = billable_line_count * per_line
    if apply_withhold:
        withheld = floor_int(D(gross) * D(WAIVER_WITHHOLD_BPS) / D(10000))
    else:
        withheld = 0
    cleaning_subtotal_cents = gross - withheld
    charge = int(visit_base_fee_cents) + cleaning_subtotal_cents + int(parts_charge_cents)
    return {
        "per_line_amount_cents": per_line,
        "withheld_cents": withheld,
        "cleaning_subtotal_cents": cleaning_subtotal_cents,
        "charge_cents": charge,
    }


# ------------------------------------------------- 4. yield_loss_estimate (PRD 3.8)

def days_at_risk(reported_at, baseline_at):
    return min(MAX_DAYS_AT_RISK, max(0, whole_days_between(reported_at, baseline_at)))


def provisional_yield_loss(symptom, risk_days, average_daily_throughput_liters):
    liters = rhu(SEVERITY_FACTOR[symptom] * D(risk_days)
                 * D(average_daily_throughput_liters), 2)
    cents = rhu_int(liters * WHOLESALE_CENTS_PER_LITER)
    return liters, cents


def settled_yield_loss(measured_waste_liters, reported_at, resolved_at):
    days_open = whole_days_between(resolved_at, reported_at) + 1
    liters = rhu(D(measured_waste_liters)
                 + FOAM_ALLOWANCE_LITERS_PER_DAY * D(days_open), 2)
    cents = rhu_int(liters * WHOLESALE_CENTS_PER_LITER)
    return liters, cents, days_open


# -------------------------------------------- 5. brewer_funding_waterfall (PRD 3.7)

def funding_waterfall(funded_scope, co_pay_bps, funding_cap_cents, consumed_cents,
                      cleaning_cents, parts_cents, base_fee_cents):
    eligible = FUNDED_SCOPE_BUCKETS[funded_scope]
    amounts = {"CLEANING": int(cleaning_cents), "PARTS": int(parts_cents),
               "BASE_FEE": int(base_fee_cents)}
    headroom = int(funding_cap_cents) - int(consumed_cents)
    granted = 0
    for bucket in BUCKET_ORDER:
        if bucket not in eligible:
            continue
        amount = amounts[bucket]
        share = floor_int(D(amount) * D(10000 - int(co_pay_bps)) / D(10000))
        grant = max(0, min(share, headroom - granted))
        granted += grant
    return granted


# ------------------------------------------------- 6. glycol_health_score (PRD 3.9)

def glycol_health(glycol_pct, pump_psi, last_serviced_at, current_utc, window_temps):
    """window_temps: cooler_temp_f of the newest READING_WINDOW readings."""
    window = list(window_temps)[:READING_WINDOW]
    if window:
        total = D(0)
        for value in window:
            total += D(value)
        window_avg = rhu(total / D(len(window)), 2)
        temp_penalty = max(D("0.0"),
                           rhu((window_avg - TARGET_COOLER_TEMP_F)
                               * TEMP_PENALTY_PER_DEGREE, 2))
    else:
        window_avg = None
        temp_penalty = D("0.00")
    glycol_penalty = max(D("0.0"),
                         rhu((MIN_GLYCOL_PCT - D(glycol_pct)) * GLYCOL_PENALTY_PER_PCT, 2))
    pump_penalty = PUMP_PENALTY_FLAT if D(pump_psi) < MIN_PUMP_PSI else D("0.0")
    days_since_service = max(0, whole_days_between(current_utc, last_serviced_at))
    service_penalty = rhu(D(max(0, days_since_service - GLYCOL_SERVICE_INTERVAL_DAYS))
                          * SERVICE_PENALTY_PER_DAY, 2)
    raw = D(100) - temp_penalty - glycol_penalty - pump_penalty - service_penalty
    health_score = rhu(min(D(100), max(D(0), raw)), 2)
    if health_score >= WATCH_THRESHOLD:
        status = "NORMAL"
    elif health_score >= ALARM_THRESHOLD:
        status = "WATCH"
    else:
        status = "ALARM"
    return {
        "window_avg_cooler_temp_f": window_avg,
        "health_score": health_score,
        "status": status,
    }
