"""Deterministic calculations, constants and the rounding discipline (PRD 2.6).

Every arithmetic step runs in Decimal and every rounding step is ROUND_HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP

# --- forecast_load_projection -------------------------------------------------
OCCUPANCY_FACTOR = {
    "WEEKDAY_FULL": Decimal("1.00"),
    "WEEKEND_REDUCED": Decimal("0.72"),
    "HOLIDAY_MINIMAL": Decimal("0.45"),
}
CLASS_DIVERSITY_FACTOR = {
    "RESIDENTIAL_MULTIFAMILY": Decimal("0.62"),
    "COMMERCIAL_OFFICE": Decimal("0.78"),
    "HOSPITAL": Decimal("0.90"),
    "UNIVERSITY": Decimal("0.70"),
    "INDUSTRIAL_PROCESS": Decimal("0.95"),
}
HDH_KW_PER_DEGREE_HOUR = Decimal("3.5")
CDH_KW_PER_DEGREE_HOUR = Decimal("2.8")
DISTRIBUTION_LOSS_FACTOR = Decimal("0.08")
DISPATCH_BLOCK_HOURS = Decimal("24")
FORECAST_LOAD_FACTOR = Decimal("0.62")
ACTUAL_WEIGHT = Decimal("0.70")

# --- merit_order_dispatch / plan_reliability_metrics --------------------------
STORAGE_DISCHARGE_HOURS = Decimal("4")
MIN_RESERVE_MARGIN_PCT = Decimal("15.0")
MAX_FUEL_DIVERSITY_HHI = Decimal("0.55")

# --- invoice_billing_determinants / agreement_balance_ledger -----------------
RESERVED_FLOOR_PCT = Decimal("0.50")
ARREARS_THRESHOLD_AMOUNT = Decimal("25000.00")

# --- segment_leak_risk_score --------------------------------------------------
W_AGE = Decimal("0.35")
W_MAKEUP = Decimal("0.30")
W_HIST = Decimal("0.20")
W_INSUL = Decimal("0.15")
AGE_FULL_YEARS = Decimal("60")
MAKEUP_FULL_RATIO = Decimal("0.05")
HIST_FULL_COUNT = Decimal("3")
INSULATION_PENALTY = {"A": Decimal("0.10"), "B": Decimal("0.45"), "C": Decimal("0.85")}
MONITORED_SCORE_FLOOR = Decimal("45.0")
SUSPECT_SCORE_FLOOR = Decimal("70.0")

# --- loop_capacity_reservation_sweep -----------------------------------------
OVERSUBSCRIPTION_FACTOR = Decimal("1.15")

# --- work_window_conflict_detection ------------------------------------------
REFILL_BUFFER_HOURS = 6

# --- expansion_sizing_and_npv ------------------------------------------------
FLOW_COEFF_KW_PER_M3H_K = Decimal("1.163")
PI = Decimal("3.14159265")
FRICTION_COEFF = Decimal("0.01")
STANDARD_DIAMETERS_MM = [80, 100, 125, 150, 200, 250, 300, 400]
MAX_VELOCITY_M_S = Decimal("2.0")
MAX_PRESSURE_DROP_KPA_PER_KM = Decimal("100.0")
COST_PER_MM_PER_M = Decimal("9.5")
CONNECTION_FIXED_CAPEX = Decimal("85000.00")
ANNUAL_OPEX_RATE = Decimal("0.025")
PV_ANNUITY_FACTOR_20Y_6PCT = Decimal("11.46992122")
MONTHS_PER_YEAR = Decimal("12")

# --- loop_emissions_efficiency_summary ---------------------------------------
CITY_TARGET_KG_PER_MWH = Decimal("150.0")

ZERO = Decimal("0")


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def rnd(value, places):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def r2(value):
    return rnd(value, 2)


def r3(value):
    return rnd(value, 3)


def r4(value):
    return rnd(value, 4)


def r6(value):
    return rnd(value, 6)


def f(value):
    return float(value)


# =============================================================================
# 1. forecast_load_projection
# =============================================================================
def forecast_load_projection(forecast, variant, agreements):
    """agreements: input set already filtered and ordered created_at ASC."""
    occupancy = OCCUPANCY_FACTOR[forecast["occupancy_profile"]]
    if variant == "WEATHER_NORMAL_PROVISIONAL":
        hdh = D(forecast["heating_degree_hours"])
        cdh = D(forecast["cooling_degree_hours"])
    else:
        hdh = r2(ACTUAL_WEIGHT * D(forecast["actual_heating_degree_hours"])
                 + (Decimal("1") - ACTUAL_WEIGHT) * D(forecast["heating_degree_hours"]))
        cdh = r2(ACTUAL_WEIGHT * D(forecast["actual_cooling_degree_hours"])
                 + (Decimal("1") - ACTUAL_WEIGHT) * D(forecast["cooling_degree_hours"]))
    weather_kw = r2(hdh * HDH_KW_PER_DEGREE_HOUR + cdh * CDH_KW_PER_DEGREE_HOUR)

    diversified = ZERO
    for agreement in agreements:
        contribution = r2(D(agreement["reserved_capacity_kw"])
                          * CLASS_DIVERSITY_FACTOR[agreement["customer_class"]]
                          * occupancy)
        diversified = diversified + contribution

    coincident = r2((diversified + weather_kw) * (Decimal("1") + DISTRIBUTION_LOSS_FACTOR))
    energy = r3(coincident * DISPATCH_BLOCK_HOURS * FORECAST_LOAD_FACTOR / Decimal("1000"))
    return {
        "coincident_demand_kw": f(coincident),
        "projected_energy_mwh": f(energy),
        "contributing_agreement_count": len(agreements),
        "variant_applied": variant,
    }


# =============================================================================
# 2. merit_order_dispatch + 3. plan_reliability_metrics
# =============================================================================
def effective_capacity_kw(asset):
    if asset["asset_type"] == "THERMAL_STORAGE":
        sized = r2(D(asset["storage_capacity_kwh"]) / STORAGE_DISCHARGE_HOURS)
        rated = D(asset["rated_capacity_kw"])
        return sized if sized < rated else rated
    if asset["availability_state"] == "DERATED":
        return D(asset["derated_capacity_kw"])
    return D(asset["rated_capacity_kw"])


def merit_order_sort_key(asset):
    return (D(asset["marginal_cost_per_mwh"]),
            D(asset["emission_factor_kg_per_mwh"]),
            asset["created_at"],
            asset["_seq"])


def merit_order_dispatch(eligible, demand_kw):
    """Returns (list of order payloads, plan roll-up dict)."""
    ranked = sorted(eligible, key=merit_order_sort_key)
    remaining = D(demand_kw)
    rank = 0
    orders = []
    for asset in ranked:
        storage = asset["asset_type"] == "THERMAL_STORAGE"
        effective = effective_capacity_kw(asset)
        block = effective if effective < remaining else remaining
        if block <= ZERO:
            continue
        if block < D(asset["min_stable_output_kw"]):
            continue
        rank = rank + 1
        hours = STORAGE_DISCHARGE_HOURS if storage else DISPATCH_BLOCK_HOURS
        block_energy = r3(block * hours / Decimal("1000"))
        discharged = r2(block * STORAGE_DISCHARGE_HOURS) if storage else Decimal("0.0")
        cost = r2(block_energy * D(asset["marginal_cost_per_mwh"]))
        emissions = r2(block_energy * D(asset["emission_factor_kg_per_mwh"]))
        orders.append({
            "asset": asset,
            "merit_rank": rank,
            "allocated_kw": f(r2(block)),
            "block_energy_mwh": f(block_energy),
            "discharged_kwh": f(discharged),
            "order_cost": f(cost),
            "order_emissions_kg": f(emissions),
        })
        remaining = r2(remaining - block)
        if remaining <= ZERO:
            break

    unserved = remaining if remaining > ZERO else Decimal("0.0")
    totals = {
        "allocated_capacity_kw": f(r2(sum((D(o["allocated_kw"]) for o in orders), ZERO))),
        "unserved_demand_kw": f(r2(unserved)),
        "total_dispatch_cost": f(r2(sum((D(o["order_cost"]) for o in orders), ZERO))),
        "total_emissions_kg": f(r2(sum((D(o["order_emissions_kg"]) for o in orders), ZERO))),
    }
    return orders, totals


def plan_reliability_metrics(eligible, demand_kw, orders, fuel_key_of):
    available = r2(sum((effective_capacity_kw(a) for a in eligible), ZERO))
    largest = ZERO
    for asset in sorted(eligible, key=lambda a: (a["created_at"], a["_seq"])):
        capacity = effective_capacity_kw(asset)
        if capacity > largest:
            largest = capacity
    n1_available = r2(available - largest)
    demand = D(demand_kw)
    if demand == ZERO:
        margin = Decimal("0.0")
    else:
        margin = r2((n1_available - demand) / demand * Decimal("100"))

    total_mwh = r3(sum((D(o["block_energy_mwh"]) for o in orders), ZERO))
    if total_mwh == ZERO:
        hhi = Decimal("0.0")
    else:
        per_key = {}
        for order in orders:
            key = fuel_key_of(order)
            per_key[key] = per_key.get(key, ZERO) + D(order["block_energy_mwh"])
        accumulated = ZERO
        for key in per_key:
            share = r3(per_key[key]) / total_mwh
            accumulated = accumulated + share * share
        hhi = r4(accumulated)
    return {"reserve_margin_pct": f(r2(margin)), "fuel_diversity_hhi": f(hhi)}


# =============================================================================
# 4. invoice_billing_determinants
# =============================================================================
def invoice_billing_determinants(agreement, rate, variant, readings, points_by_id,
                                 period_hours):
    """readings: admitted set ordered by read_at ASC then created_at ASC."""
    by_point = {}
    order_of_points = []
    for reading in readings:
        point_id = reading["point_id"]
        if point_id not in by_point:
            by_point[point_id] = []
            order_of_points.append(point_id)
        by_point[point_id].append(reading)

    billed_energy = ZERO
    for point_id in order_of_points:
        group = by_point[point_id]
        if len(group) < 2:
            continue
        raw_delta = D(group[-1]["cumulative_energy_mwh"]) - D(group[0]["cumulative_energy_mwh"])
        point_energy = r3(raw_delta * D(points_by_id[point_id]["multiplier"]))
        billed_energy = billed_energy + point_energy
    billed_energy = r3(billed_energy)

    metered_peak = ZERO
    for reading in readings:
        peak = D(reading["peak_demand_kw"])
        if peak > metered_peak:
            metered_peak = peak

    reserved_floor = r2(D(agreement["reserved_capacity_kw"]) * RESERVED_FLOOR_PCT)
    ratchet = ZERO if variant == "ESTIMATED" else D(agreement["billed_demand_ratchet_kw"])
    billed_demand = r2(max(metered_peak, reserved_floor, ratchet))

    if billed_demand == ZERO or period_hours <= 0:
        load_factor = Decimal("0.0")
    else:
        load_factor = r2(billed_energy * Decimal("1000")
                         / (billed_demand * D(period_hours)) * Decimal("100"))

    tiers = rate["tiers"]
    chosen = tiers[-1]
    for tier in tiers:
        if D(tier["load_factor_max"]) >= load_factor:
            chosen = tier
            break

    energy_charge = r2(billed_energy * D(chosen["energy_rate_per_mwh"]))
    demand_charge = r2(billed_demand * D(rate["demand_charge_per_kw"]))
    fixed_charge = D(rate["fixed_service_charge"])
    subtotal = r2(energy_charge + demand_charge + fixed_charge)
    minimum = D(rate["minimum_bill_amount"])
    if subtotal < minimum:
        total = minimum
        minimum_applied = True
    else:
        total = subtotal
        minimum_applied = False

    return {
        "billed_energy_mwh": f(billed_energy),
        "billed_demand_kw": f(billed_demand),
        "load_factor_pct": f(load_factor),
        "energy_charge": f(energy_charge),
        "demand_charge": f(demand_charge),
        "fixed_charge": f(fixed_charge),
        "total_amount": f(total),
        "minimum_bill_applied": minimum_applied,
        "variant_applied": variant,
    }


# =============================================================================
# 5. segment_leak_risk_score
# =============================================================================
def segment_leak_risk_score(segment, clock_year):
    age_years = D(clock_year - int(segment["install_year"]))
    age_ratio = age_years / AGE_FULL_YEARS
    if age_ratio > Decimal("1"):
        age_ratio = Decimal("1")
    age_component = r2(age_ratio * Decimal("100"))

    makeup_ratio = D(segment["makeup_water_ratio"]) / MAKEUP_FULL_RATIO
    if makeup_ratio > Decimal("1"):
        makeup_ratio = Decimal("1")
    makeup_component = r2(makeup_ratio * Decimal("100"))

    hist_ratio = D(segment["historical_leak_count"]) / HIST_FULL_COUNT
    if hist_ratio > Decimal("1"):
        hist_ratio = Decimal("1")
    hist_component = r2(hist_ratio * Decimal("100"))

    insul_component = r2(INSULATION_PENALTY[segment["insulation_class"]] * Decimal("100"))

    score = r2(W_AGE * age_component + W_MAKEUP * makeup_component
               + W_HIST * hist_component + W_INSUL * insul_component)
    return score


def band_for_score(score):
    score = D(score)
    if score >= SUSPECT_SCORE_FLOOR:
        return "SUSPECT"
    if score >= MONITORED_SCORE_FLOOR:
        return "MONITORED"
    return "SOUND"


# =============================================================================
# 6. loop_capacity_reservation_sweep
# =============================================================================
def loop_capacity_reservation_sweep(loop, candidate, peers):
    ceiling = r2(D(loop["rated_capacity_kw"]) * OVERSUBSCRIPTION_FACTOR)
    windows = list(peers) + [candidate]
    boundaries = []
    for window in windows:
        start = window["_service_start_date"]
        if start not in boundaries:
            boundaries.append(start)
    boundaries.sort()
    for boundary in boundaries:
        total = ZERO
        for window in windows:
            if window["_service_start_date"] <= boundary < window["_service_end_date"]:
                total = total + D(window["reserved_capacity_kw"])
        if r2(total) > ceiling:
            return False
    return True


# =============================================================================
# 7. work_window_conflict_detection
# =============================================================================
def work_window_conflict(candidate, peers):
    from datetime import timedelta
    buffer_delta = timedelta(hours=REFILL_BUFFER_HOURS)
    candidate_end = candidate["_window_end"] + buffer_delta
    for peer in peers:
        peer_end = peer["_window_end"] + buffer_delta
        if candidate["_window_start"] <= peer_end and peer["_window_start"] <= candidate_end:
            return True
    return False


# =============================================================================
# 8. expansion_sizing_and_npv
# =============================================================================
def expansion_sizing_and_npv(inputs, rate):
    """Returns the output dict, or None when no standard diameter is feasible."""
    flow = r3(D(inputs["requested_capacity_kw"])
              / (FLOW_COEFF_KW_PER_M3H_K * D(inputs["design_delta_t_c"])))

    selected = None
    for diameter in STANDARD_DIAMETERS_MM:
        metres = D(diameter) / Decimal("1000")
        area = r6(PI * metres * metres / Decimal("4"))
        if area == ZERO:
            continue
        velocity = r4(flow / Decimal("3600") / area)
        drop = r2(FRICTION_COEFF * velocity * velocity / metres * Decimal("1000"))
        if velocity <= MAX_VELOCITY_M_S and drop <= MAX_PRESSURE_DROP_KPA_PER_KM:
            selected = diameter
            break
    if selected is None:
        return None

    capex = r2(D(selected) * D(inputs["route_length_m"]) * COST_PER_MM_PER_M
               + CONNECTION_FIXED_CAPEX)

    fallback = rate["tiers"][0]
    for tier in rate["tiers"]:
        if D(tier["load_factor_max"]) > D(fallback["load_factor_max"]):
            fallback = tier

    revenue = r2(D(inputs["assumed_annual_energy_mwh"]) * D(fallback["energy_rate_per_mwh"])
                 + D(inputs["requested_capacity_kw"]) * D(rate["demand_charge_per_kw"])
                 * MONTHS_PER_YEAR
                 + D(rate["fixed_service_charge"]) * MONTHS_PER_YEAR)
    variable_cost = r2(D(inputs["assumed_annual_energy_mwh"])
                       * D(inputs["assumed_marginal_cost_per_mwh"]))
    fixed_opex = r2(capex * ANNUAL_OPEX_RATE)
    margin = r2(revenue - variable_cost - fixed_opex)
    npv = r2(margin * PV_ANNUITY_FACTOR_20Y_6PCT - capex)

    return {
        "design_flow_m3_per_h": f(flow),
        "selected_diameter_mm": selected,
        "estimated_capex": f(capex),
        "annual_net_margin": f(margin),
        "npv": f(npv),
    }


# =============================================================================
# 9. loop_emissions_efficiency_summary
# =============================================================================
def loop_emissions_efficiency_summary(loop_id, plans, orders):
    total_energy = r3(sum((D(o["block_energy_mwh"]) for o in orders), ZERO))
    total_emissions = r2(sum((D(o["order_emissions_kg"]) for o in orders), ZERO))
    delivered = r3(total_energy * (Decimal("1") - DISTRIBUTION_LOSS_FACTOR))
    if total_energy == ZERO:
        efficiency = Decimal("0.0")
    else:
        efficiency = r2(delivered / total_energy * Decimal("100"))
    if delivered == ZERO:
        intensity = Decimal("0.0")
    else:
        intensity = r2(total_emissions / delivered)
    gap = r2(intensity - CITY_TARGET_KG_PER_MWH)
    return {
        "loop_id": loop_id,
        "total_energy_mwh": f(total_energy),
        "delivered_energy_mwh": f(delivered),
        "total_emissions_kg": f(total_emissions),
        "system_efficiency_pct": f(efficiency),
        "emissions_intensity_kg_per_mwh": f(intensity),
        "target_gap_kg_per_mwh": f(gap),
        "climate_goal_status": "COMPLIANT" if gap <= ZERO else "EXCEEDING",
        "contributing_plan_count": len(plans),
    }


# =============================================================================
# 10. agreement_balance_ledger
# =============================================================================
def agreement_balance(invoices):
    return f(r2(sum((D(i["total_amount"]) for i in invoices), ZERO)))
