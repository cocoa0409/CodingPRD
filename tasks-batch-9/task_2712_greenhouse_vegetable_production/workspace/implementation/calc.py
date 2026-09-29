"""Calculations, derived-field recomputation and cascade helpers."""
from datetime import timedelta

import const
from money import D, ZERO, dmax, dmin, q0, q1, q2, q3, q4, to_int
from store import db, now, ordered, touch

# --------------------------------------------------------------------------
# Zone posture derivation
# --------------------------------------------------------------------------


def derive_zone_status(zone):
    statuses = set()
    for cycle in db["crop_cycles"].values():
        if cycle["zone_id"] == zone["id"]:
            statuses.add(cycle["status"])
    if "PRODUCTION" in statuses:
        return "HARVESTING"
    if "TERMINATION_SCHEDULED" in statuses:
        return "TURNAROUND"
    if statuses & {"PLANNED", "TRANSPLANTED"}:
        return "PLANTED"
    return "IDLE"


def derive_ipm_posture(zone):
    clear_at = zone.get("reentry_clear_at")
    if clear_at is not None and now() < clear_at:
        return "LOCKED"
    if zone["open_pest_alert_count"] >= const.PEST_ALERT_LOCK_COUNT:
        return "LOCKED"
    if zone["open_pest_alert_count"] >= 1:
        return "SCOUT_ALERT"
    return "NORMAL"


def derive_irrigation_posture(zone):
    count = zone["drain_alarm_count"]
    if count >= const.DRAIN_ALARM_LOCK_COUNT:
        return "LOCKED"
    if count == const.DRAIN_ALARM_WATCH_COUNT:
        return "WATCH"
    return "NORMAL"


def recompute_hive_slots(zone):
    total = 0
    for cycle in db["crop_cycles"].values():
        if cycle["zone_id"] != zone["id"]:
            continue
        if cycle["status"] in const.CYCLE_OCCUPYING:
            total += cycle.get("hive_count_placed") or 0
    zone["hive_slots_used"] = total


def recompute_zone_budget(zone):
    committed = ZERO
    for task in db["labor_tasks"].values():
        if task["zone_id"] != zone["id"]:
            continue
        if task["status"] in const.TASK_COMMITTED:
            committed += D(task["planned_cost_usd"])
        elif task["status"] == "COMPLETED":
            committed += D(task.get("actual_cost_usd") or 0)
    zone["labor_budget_committed_usd"] = q2(committed)
    zone["labor_budget_remaining_usd"] = q2(
        D(zone["labor_budget_usd"]) - zone["labor_budget_committed_usd"]
    )


def refresh_zone(zone, force=False):
    """Re-derive every computed zone field; bump version when anything moved."""
    before = (
        zone["status"], zone["ipm_posture"], zone["irrigation_posture"],
        zone["hive_slots_used"], zone["labor_budget_committed_usd"],
        zone["labor_budget_remaining_usd"], zone["open_pest_alert_count"],
        zone["drain_alarm_count"], zone["reentry_clear_at"],
        zone["climate_plan_revision"],
    )
    zone["status"] = derive_zone_status(zone)
    zone["ipm_posture"] = derive_ipm_posture(zone)
    zone["irrigation_posture"] = derive_irrigation_posture(zone)
    recompute_hive_slots(zone)
    recompute_zone_budget(zone)
    after = (
        zone["status"], zone["ipm_posture"], zone["irrigation_posture"],
        zone["hive_slots_used"], zone["labor_budget_committed_usd"],
        zone["labor_budget_remaining_usd"], zone["open_pest_alert_count"],
        zone["drain_alarm_count"], zone["reentry_clear_at"],
        zone["climate_plan_revision"],
    )
    if force or before != after:
        touch(zone)
    return zone


def zone_of_cycle(cycle):
    return db["zones"].get(cycle["zone_id"])


def recompute_worker_hours(worker):
    total = ZERO
    for task in db["labor_tasks"].values():
        if task["worker_id"] != worker["id"]:
            continue
        if task["status"] in const.TASK_COMMITTED:
            total += D(task["planned_hours"])
    value = q2(total)
    if value != worker["committed_hours"]:
        worker["committed_hours"] = value
        touch(worker)


# --------------------------------------------------------------------------
# expected_yield_curve
# --------------------------------------------------------------------------


def project_yield(cycle):
    """Round each weekly figure to two decimals BEFORE summing (round-then-sum)."""
    zone = db["zones"][cycle["zone_id"]]
    variety = db["varieties"][cycle["variety_id"]]
    area = D(zone["area_sqft"])
    nominal_plants = area * D(variety["plant_density_per_sqft"])
    if nominal_plants == 0:
        density_factor = ZERO
    else:
        density_factor = dmin(
            q4(D(cycle["plants_transplanted"]) / nominal_plants),
            const.MAX_DENSITY_FACTOR,
        )
    weekly = []
    for entry in variety["yield_curve_lbs_per_sqft"]:
        weekly.append(q2(D(entry) * area * density_factor))
    baseline = ZERO
    for value in weekly:
        baseline += value
    baseline = q2(baseline)
    haircut = D(cycle.get("pollination_haircut_pct") or 0)
    expected_total = q2(baseline * (D(1) - haircut / D(100)))
    cycle["density_factor"] = density_factor
    cycle["expected_weekly_yield_lbs"] = weekly
    cycle["baseline_total_yield_lbs"] = baseline
    cycle["expected_total_yield_lbs"] = expected_total
    recompute_variance(cycle)


def recompute_variance(cycle):
    expected = D(cycle["expected_total_yield_lbs"] or 0)
    cumulative = D(cycle["cumulative_harvested_lbs"] or 0)
    if expected == 0:
        cycle["yield_variance_pct"] = q2(0)
    else:
        cycle["yield_variance_pct"] = q2(
            D(100) * (cumulative - expected) / expected
        )


def recompute_cumulative_harvest(cycle):
    total = ZERO
    for lot in db["harvest_lots"].values():
        if lot["crop_cycle_id"] != cycle["id"]:
            continue
        if lot["cold_chain_status"] == "REJECTED":
            continue
        total += D(lot["gross_weight_lbs"])
    cycle["cumulative_harvested_lbs"] = q2(total)
    recompute_variance(cycle)


# --------------------------------------------------------------------------
# pollination_strength_decay
# --------------------------------------------------------------------------


def pollination_check(cycle, observed_at, flower_visit_pct, hive_activity_count):
    variety = db["varieties"][cycle["variety_id"]]
    placed_at = cycle.get("hives_placed_at")
    if placed_at is None:
        weeks = 0
    else:
        elapsed = (observed_at - placed_at).total_seconds()
        weeks = int(elapsed // (7 * 24 * 3600))
    base = q2(D(100) * (const.HIVE_DECAY_BASE ** weeks))
    penalty = ZERO
    visit = D(flower_visit_pct)
    if visit < const.LOW_VISIT_PCT:
        penalty += const.LOW_BAND_PENALTY
    elif visit < const.TARGET_VISIT_PCT:
        penalty += const.MID_BAND_PENALTY
    if hive_activity_count < const.MIN_ACTIVITY_COUNT:
        penalty += const.LOW_ACTIVITY_PENALTY
    index = q2(dmax(ZERO, dmin(D(100), base - penalty)))
    risk = q2(D(100) - index)
    if not variety["requires_pollination"]:
        haircut = q2(0)
    elif risk >= const.POLLINATION_RISK_THRESHOLD:
        haircut = q2(const.POLLINATION_HAIRCUT_PCT)
    else:
        haircut = q2(0)
    cycle["pollination_strength_index"] = index
    cycle["pollination_risk_score"] = risk
    cycle["pollination_haircut_pct"] = haircut
    project_yield(cycle)
    return weeks, base


# --------------------------------------------------------------------------
# energy_cost
# --------------------------------------------------------------------------


def window_hours(start, end):
    return q2(D((end - start).total_seconds()) / D(3600))


def project_energy(strategy, zone):
    hours = D(strategy["window_hours"])
    area = D(zone["area_sqft"])
    screen_credit = D(1) - const.SCREEN_SAVING_FACTOR * D(
        strategy["screen_position_pct"]
    ) / D(100)
    delta_t = dmax(ZERO, D(strategy["temp_setpoint_c"]) - const.OUTSIDE_TEMP_C)
    planned_heat = q2(const.HEAT_COEFF * area * delta_t * hours * screen_credit)
    planned_light = q2(
        const.LIGHT_KW_PER_SQFT * area * D(strategy["lighting_hours"])
    )
    co2_delta = dmax(ZERO, D(strategy["co2_setpoint_ppm"]) - const.AMBIENT_CO2_PPM)
    planned_co2 = q2(const.CO2_COEFF * area * co2_delta * hours / D(100))
    projected = q2(
        planned_heat * const.GAS_USD_PER_KWH
        + planned_light * const.GRID_BUY_USD_PER_KWH
        + planned_co2 * const.CO2_USD_PER_KG
    )
    strategy["planned_heat_kwh"] = planned_heat
    strategy["planned_light_kwh"] = planned_light
    strategy["planned_co2_kg"] = planned_co2
    strategy["projected_energy_cost_usd"] = projected


def settle_energy(strategy, zone):
    gas_m3 = D(strategy["gas_consumed_m3"])
    chp_kwh = D(strategy["chp_generated_kwh"])
    grid_kwh = D(strategy["grid_import_kwh"])
    planned_heat = D(strategy["planned_heat_kwh"])
    planned_light = D(strategy["planned_light_kwh"])
    planned_co2 = D(strategy["planned_co2_kg"])

    gas_cost = q2(gas_m3 * const.GAS_USD_PER_M3)
    grid_cost = q2(grid_kwh * const.GRID_BUY_USD_PER_KWH)

    if zone["chp_connected"]:
        chp_heat_kwh = q2(chp_kwh * const.CHP_HEAT_TO_POWER)
        denominator = chp_kwh + chp_heat_kwh
        if denominator == 0:
            power_share = q4(0)
        else:
            power_share = q4(chp_kwh / denominator)
        allocated_power_cost = q2(gas_cost * power_share)
        allocated_heat_cost = q2(gas_cost - allocated_power_cost)
        co2_offset_kg = dmin(planned_co2, q2(chp_kwh * const.CO2_KG_PER_CHP_KWH))
        co2_purchase_cost = q2(
            dmax(ZERO, q2(planned_co2 - co2_offset_kg)) * const.CO2_USD_PER_KG
        )
        export_credit = q2(
            dmax(ZERO, q2(chp_kwh - planned_light)) * const.GRID_SELL_USD_PER_KWH
        )
        # Only the heat share of the gas bill is charged to the crop; the power
        # share is recovered through generation.
        settled = q2(
            allocated_heat_cost + grid_cost + co2_purchase_cost - export_credit
        )
        _ = allocated_power_cost
    else:
        co2_purchase_cost = q2(planned_co2 * const.CO2_USD_PER_KG)
        settled = q2(gas_cost + grid_cost + co2_purchase_cost)

    strategy["settled_energy_cost_usd"] = settled
    strategy["cost_variance_usd"] = q2(
        settled - D(strategy["projected_energy_cost_usd"])
    )


# --------------------------------------------------------------------------
# nutrient_blend_recirculation  (single pass; the cap is never revisited)
# --------------------------------------------------------------------------


def blend_batch(batch):
    planned = D(batch["planned_volume_liters"])
    requested = D(batch["requested_recirculated_liters"])
    reservoir_ec = D(batch["reservoir_ec_ms"])
    target_ec = D(batch["target_ec_ms"])

    provisional_fresh = planned - requested
    provisional = q3(
        (provisional_fresh * const.FRESH_WATER_EC_MS + requested * reservoir_ec)
        / planned
    )
    if provisional <= const.RECIRC_TIER1_EC:
        cap = 60
    elif provisional <= const.RECIRC_TIER2_EC:
        cap = 40
    else:
        cap = 0
    capped_volume = int((planned * D(cap) / D(100)).to_integral_value(rounding="ROUND_FLOOR"))
    applied = min(int(requested), capped_volume)
    fresh = int(planned) - applied
    blended = q3(
        (D(fresh) * const.FRESH_WATER_EC_MS + D(applied) * reservoir_ec) / planned
    )
    injector = q1(
        dmax(ZERO, target_ec - blended)
        * const.STOCK_ML_PER_EC_PER_1000L
        * planned
        / D(1000)
    )
    batch["provisional_blend_ec_ms"] = provisional
    batch["recirc_cap_pct"] = cap
    batch["recirculated_liters_applied"] = applied
    batch["fresh_liters_applied"] = fresh
    batch["blended_ec_ms"] = blended
    batch["injector_ml"] = injector


# --------------------------------------------------------------------------
# drainage_alarm_evaluation
# --------------------------------------------------------------------------


def evaluate_drainage(batch, zone, drain_volume_liters, drain_ec_ms):
    batch["drain_reading_count"] = batch["drain_reading_count"] + 1
    batch["cumulative_drain_volume_liters"] = q2(
        D(batch["cumulative_drain_volume_liters"]) + D(drain_volume_liters)
    )
    batch["last_drain_ec_ms"] = D(drain_ec_ms)
    delivered = D(batch["delivered_volume_liters"] or 0)
    if delivered == 0:
        fraction = q2(0)
    else:
        fraction = q2(
            D(100) * D(batch["cumulative_drain_volume_liters"]) / delivered
        )
    batch["drain_fraction_pct"] = fraction

    target = D(batch["drain_target_pct"])
    band_low = q2(target - const.DRAIN_BAND_TOLERANCE_PCT)
    band_high = q2(target + const.DRAIN_BAND_TOLERANCE_PCT)
    high_breach = fraction > band_high
    ec_breach = D(drain_ec_ms) > const.DRAIN_EC_ALARM_MS
    low_breach = (
        fraction < band_low
        and batch["drain_reading_count"] >= const.MIN_READINGS_FOR_LOW_ALARM
    )
    latched = False
    if (high_breach or ec_breach or low_breach) and not batch["drain_alarm"]:
        batch["drain_alarm"] = True
        zone["drain_alarm_count"] = zone["drain_alarm_count"] + 1
        latched = True
    return latched


# --------------------------------------------------------------------------
# labor_standard_cost
# --------------------------------------------------------------------------


def cost_of_hours(hours, hourly_rate):
    hours = D(hours)
    rate = D(hourly_rate)
    regular = dmin(hours, const.OT_THRESHOLD_HOURS)
    overtime = dmax(ZERO, hours - const.OT_THRESHOLD_HOURS)
    return q2(regular * rate + overtime * rate * const.OT_MULTIPLIER)


def plan_labor_cost(task, worker):
    planned_hours = q2(
        D(task["planned_units"])
        / (D(task["standard_units_per_hour"]) * D(worker["productivity_index"]))
    )
    task["planned_hours"] = planned_hours
    task["planned_cost_usd"] = cost_of_hours(planned_hours, worker["hourly_rate_usd"])


def actual_labor_cost(task, worker, actual_hours, actual_units):
    ratio = q4(
        (D(actual_units) / D(actual_hours)) / D(task["standard_units_per_hour"])
    )
    if ratio >= const.BONUS_RATIO_THRESHOLD:
        bonus = q2(D(actual_units) * const.BONUS_USD_PER_UNIT)
    else:
        bonus = q2(0)
    task["actual_hours"] = q2(actual_hours)
    task["actual_units"] = q2(actual_units)
    task["productivity_ratio"] = ratio
    task["bonus_usd"] = bonus
    task["actual_cost_usd"] = q2(
        cost_of_hours(actual_hours, worker["hourly_rate_usd"]) + bonus
    )


# --------------------------------------------------------------------------
# pest_threshold_status
# --------------------------------------------------------------------------


def pest_threshold(pest_code, pest_count_per_plant):
    pressure = q3(pest_count_per_plant)
    threshold = const.PEST_ACTION_THRESHOLDS[pest_code]
    if pressure < threshold:
        status = "BELOW"
    elif pressure == threshold:
        status = "AT"
    else:
        status = "ABOVE"
    return threshold, status, status in ("AT", "ABOVE")


# --------------------------------------------------------------------------
# lot_grading_packout
# --------------------------------------------------------------------------


def recompute_lot_pools(lot):
    for grade, allocated_key, available_key, grade_key in (
        ("A", "allocated_a_lbs", "available_a_lbs", "grade_a_lbs"),
        ("B", "allocated_b_lbs", "available_b_lbs", "grade_b_lbs"),
    ):
        total = ZERO
        for row in db["lot_allocations"].values():
            if row["lot_id"] != lot["id"] or row["grade"] != grade:
                continue
            if row["status"] in const.ALLOCATION_ACTIVE:
                total += D(row["allocated_lbs"])
        lot[allocated_key] = q2(total)
        graded = lot.get(grade_key)
        if graded is None:
            lot[available_key] = q2(0)
        else:
            lot[available_key] = q2(D(graded) - lot[allocated_key])


def apply_grading(lot, grade_a, grade_b, cull):
    lot["grade_a_lbs"] = q2(grade_a)
    lot["grade_b_lbs"] = q2(grade_b)
    lot["cull_lbs"] = q2(cull)
    lot["pack_out_pct"] = q2(
        D(100) * (q2(grade_a) + q2(grade_b)) / D(lot["gross_weight_lbs"])
    )
    recompute_lot_pools(lot)


# --------------------------------------------------------------------------
# commitment_payout
# --------------------------------------------------------------------------


def recompute_week_allocated(week):
    total = ZERO
    for row in db["lot_allocations"].values():
        if row["commitment_week_id"] != week["id"]:
            continue
        if row["status"] in const.ALLOCATION_ACTIVE:
            total += D(row["allocated_lbs"])
    week["allocated_lbs"] = q2(total)


def apply_provisional(week):
    program = db["retail_programs"][week["program_id"]]
    committed = D(week["committed_lbs"])
    allocated = D(week["allocated_lbs"])
    if committed == 0:
        week["fill_rate_pct"] = q2(0)
    else:
        week["fill_rate_pct"] = q2(D(100) * allocated / committed)
    week["provisional_shortfall_lbs"] = q2(dmax(ZERO, committed - allocated))
    week["provisional_penalty_usd"] = q2(
        week["provisional_shortfall_lbs"] * D(program["shortfall_penalty_per_lb_usd"])
    )


def recompute_week_shipped(week):
    total = ZERO
    for row in db["lot_allocations"].values():
        if row["commitment_week_id"] != week["id"]:
            continue
        if row["status"] == "RELEASED":
            total += D(row["allocated_lbs"])
    week["shipped_lbs"] = q2(total)


def apply_final(week):
    program = db["retail_programs"][week["program_id"]]
    committed = D(week["committed_lbs"])
    shipped = D(week["shipped_lbs"])
    if committed == 0:
        week["fill_rate_pct"] = q2(0)
    else:
        week["fill_rate_pct"] = q2(D(100) * shipped / committed)
    week["final_shortfall_lbs"] = q2(dmax(ZERO, committed - shipped))
    week["final_penalty_usd"] = q2(
        week["final_shortfall_lbs"] * D(program["shortfall_penalty_per_lb_usd"])
    )
    week["gross_revenue_usd"] = q2(shipped * D(program["price_per_lb_usd"]))
    week["net_payout_usd"] = q2(
        week["gross_revenue_usd"] - week["final_penalty_usd"]
    )
    program["penalty_accrued_usd"] = q2(
        D(program["penalty_accrued_usd"]) + week["final_penalty_usd"]
    )
    touch(program)


def restate_week_after_allocation_change(week):
    """Hop: recompute the week's figures and revert a short ALLOCATED week to OPEN.

    Returns True when the week fell back from ALLOCATED to OPEN.
    """
    recompute_week_allocated(week)
    apply_provisional(week)
    reverted = False
    if week["status"] == "ALLOCATED" and D(week["allocated_lbs"]) < D(week["committed_lbs"]):
        week["status"] = "OPEN"
        reverted = True
    touch(week)
    return reverted


# --------------------------------------------------------------------------
# commitment_waterfall_allocation
# --------------------------------------------------------------------------


def run_waterfall(week_start_date):
    from store import base_record

    programs = db["retail_programs"]
    targets = []
    for week in db["commitment_weeks"].values():
        if week["week_start_date"] != week_start_date:
            continue
        if week["status"] != "OPEN":
            continue
        program = programs.get(week["program_id"])
        if program is None or program["status"] != "ACTIVE":
            continue
        targets.append(week)
    targets.sort(
        key=lambda w: (
            programs[w["program_id"]]["priority_rank"],
            programs[w["program_id"]]["created_at"],
            programs[w["program_id"]]["_seq"],
        )
    )

    window_end = week_start_date + timedelta(days=const.LOT_ELIGIBILITY_WINDOW_DAYS)
    candidates = []
    for lot in db["harvest_lots"].values():
        if lot["grading_status"] not in ("GRADED", "REGRADED"):
            continue
        if lot["cold_chain_status"] not in ("PRECOOLED", "COLD_HELD"):
            continue
        if not (week_start_date <= lot["harvest_date"] < window_end):
            continue
        candidates.append(lot)
    candidates.sort(key=lambda l: (l["harvest_date"], l["created_at"], l["_seq"]))
    if not candidates:
        # priority 40 - an empty candidate set rejects the whole run
        from errors import ApiError

        raise ApiError("ERR_NO_ELIGIBLE_LOTS")

    touched_lots = set()
    for target in targets:
        program = programs[target["program_id"]]
        need = q2(D(target["committed_lbs"]) - D(target["allocated_lbs"]))
        grades = ["A"] if program["grade_spec"] == "A_ONLY" else ["A", "B"]
        for grade in grades:
            pool_key = "available_a_lbs" if grade == "A" else "available_b_lbs"
            for lot in candidates:
                if need <= 0:
                    break
                pool = D(lot[pool_key])
                take = dmin(need, pool)
                if take <= 0:
                    continue
                row = base_record()
                row.update({
                    "lot_id": lot["id"],
                    "commitment_week_id": target["id"],
                    "grade": grade,
                    "allocated_lbs": q2(take),
                    "allocated_at": now(),
                    "status": "PROVISIONAL",
                    "revoked_reason": None,
                })
                db["lot_allocations"][row["id"]] = row
                recompute_lot_pools(lot)
                touched_lots.add(lot["id"])
                need = q2(need - take)
        recompute_week_allocated(target)
        if D(target["allocated_lbs"]) >= D(target["committed_lbs"]):
            target["status"] = "ALLOCATED"
        else:
            target["status"] = "OPEN"
        apply_provisional(target)
        touch(target)

    for lot_id in touched_lots:
        touch(db["harvest_lots"][lot_id])

    return targets, candidates


# --------------------------------------------------------------------------
# Cascades
# --------------------------------------------------------------------------


def revoke_rows(rows, reason):
    """Hop 1 of every unwind: flip the rows themselves to REVOKED."""
    lot_ids = []
    week_ids = []
    for row in rows:
        row["status"] = "REVOKED"
        row["revoked_reason"] = reason
        touch(row)
        if row["lot_id"] not in lot_ids:
            lot_ids.append(row["lot_id"])
        if row["commitment_week_id"] not in week_ids:
            week_ids.append(row["commitment_week_id"])
    return lot_ids, week_ids


def restore_lots(lot_ids, skip_lot_id=None):
    """Hop 2: restore each affected lot's availability pools."""
    for lot_id in lot_ids:
        lot = db["harvest_lots"].get(lot_id)
        if lot is None:
            continue
        recompute_lot_pools(lot)
        if lot_id != skip_lot_id:
            touch(lot)


def restate_weeks(week_ids, allow_revert=True):
    """Hops 3 and 4: restate week figures, then flag the programs that slipped."""
    for week_id in week_ids:
        week = db["commitment_weeks"].get(week_id)
        if week is None:
            continue
        recompute_week_allocated(week)
        apply_provisional(week)
        reverted = False
        if (
            allow_revert
            and week["status"] == "ALLOCATED"
            and D(week["allocated_lbs"]) < D(week["committed_lbs"])
        ):
            week["status"] = "OPEN"
            reverted = True
        touch(week)
        if reverted:
            program = db["retail_programs"].get(week["program_id"])
            if program is not None:
                program["at_risk_week_count"] = program["at_risk_week_count"] + 1
                touch(program)


def cancel_task(task, reason):
    """Cancel a task and repay its commitment, exactly as a manual cancel does."""
    task["status"] = "CANCELLED"
    task["cancel_reason"] = reason
    touch(task)
    worker = db["workers"].get(task["worker_id"])
    if worker is not None:
        recompute_worker_hours(worker)


def cascade_ipm_lock(zone):
    """Cancel every scheduled future harvest task in a freshly locked zone."""
    current = now()
    affected_cycles = set()
    for task in ordered("labor_tasks", lambda t: t["zone_id"] == zone["id"]):
        if task["status"] != "SCHEDULED":
            continue
        if task["task_type"] != "HARVEST":
            continue
        if task["window_start"] < current:
            continue
        cancel_task(task, const.CANCEL_REASON_IPM)
        affected_cycles.add(task["crop_cycle_id"])
    for cycle_id in affected_cycles:
        cycle = db["crop_cycles"].get(cycle_id)
        if cycle is not None and not cycle["labor_shortfall_flag"]:
            cycle["labor_shortfall_flag"] = True
            touch(cycle)


def cascade_abort_tasks(cycle):
    for task in ordered("labor_tasks", lambda t: t["crop_cycle_id"] == cycle["id"]):
        if task["status"] not in const.TASK_COMMITTED:
            continue
        cancel_task(task, const.CANCEL_REASON_ABORT)
