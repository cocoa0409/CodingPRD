"""All thirteen calculations of SCAFFOLD 1.3 / PRD 3, with their pinned
constants, evaluation orders and rounding points."""

from decimal import Decimal

from util import D, rhu, whole_minutes

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
CHLORIDE_CEILING_PPM = 250
MAX_ASSAYS = 3
ASSAY_VALIDITY_DAYS = 30

DIHYDRATE_TO_HEMIHYDRATE_FACTOR = D("0.8437")
INERT_PASSTHROUGH_FACTOR = D("1.0")

COMBINED_WATER_MIN = D("4.20")
COMBINED_WATER_MAX = D("6.50")
FREE_WATER_PASS_MAX = D("0.30")
FREE_WATER_FAIL_MAX = D("0.50")
SET_TIME_PASS_MIN = D("4.00")
SET_TIME_PASS_MAX = D("12.00")
SET_TIME_FAIL_MIN = D("3.00")
SET_TIME_FAIL_MAX = D("15.00")

PAPER_TENSION_BASE_FPM = D("250")
PAPER_TENSION_PER_FPM = D("0.06")

LATENT_HEAT_BTU_PER_LB = D("1150")
KILN_HOLD_MMBTU_PER_MIN = D("0.004")
KILN_EVAP_LB_PER_MIN_PER_MSF = D("38.0")
SPEED_PENALTY_FLOOR_FPM = D("350")
SPEED_PENALTY_PER_FPM = D("0.0004")
THICKNESS_MULTIPLIER_SLOPE = D("0.6")
THICKNESS_MULTIPLIER_CAP = D("1.35")
MOISTURE_TOLERANCE_PCT = D("0.10")
FIRE_RATED_ADDER_MMBTU_PER_MSF = {
    "REGULAR": D("0.0"),
    "TYPE_X": D("0.018"),
    "TYPE_C": D("0.026"),
    "MOLD_RESISTANT": D("0.010"),
    "ABUSE_RESISTANT": D("0.014"),
}

COLD_START_MINUTES = 45
FIRE_RATED_PURGE_MINUTES = 25

MIN_SPECIMENS_FOR_RELEASE = 3
DOWNGRADE_FAIL_RATE_CEILING = D("0.2500")

FROZEN_HELD_RUN_THRESHOLD = 3
RESTRICTED_STUCCO_FLOOR_TONS = D("40.0")

PLANNED_OUTAGE_INDEX_CEILING = D("0.90")
MAX_DEFERRALS = 2
HOUSING_SEASONALITY_INDEX = {
    1: D("0.62"),
    2: D("0.66"),
    3: D("0.85"),
    4: D("1.05"),
    5: D("1.18"),
    6: D("1.24"),
    7: D("1.20"),
    8: D("1.16"),
    9: D("1.06"),
    10: D("0.90"),
    11: D("0.80"),
    12: D("0.68"),
}

TRAILER_MAX_LB = D("48000")
TRAILER_TARGET_LB = D("44000")
OVERWEIGHT_USD_PER_LB = D("0.02")

ZONE_TABLE = (
    (D("150"), "ZONE_1", D("8.50")),
    (D("350"), "ZONE_2", D("12.75")),
    (D("600"), "ZONE_3", D("17.40")),
)
ZONE_FALLBACK = ("ZONE_4", D("23.10"))


# --------------------------------------------------------------------------
# 1. lot_assay_disposition
# --------------------------------------------------------------------------
def lot_assay_disposition(lot, plant, free_moisture_pct, purity_pct, chloride_ppm):
    """Pinned order; the FIRST failure decides quarantine_reason."""
    if lot["source_type"] == "SYNTHETIC" and D(free_moisture_pct) > D(
        plant["synthetic_free_moisture_ceiling_pct"]
    ):
        return "QUARANTINED", "MOISTURE_CEILING"
    if lot["source_type"] == "NATURAL" and D(purity_pct) < D(
        plant["natural_gypsum_purity_floor_pct"]
    ):
        return "QUARANTINED", "PURITY_FLOOR"
    if int(chloride_ppm) >= CHLORIDE_CEILING_PPM:
        return "QUARANTINED", "CHLORIDE_CEILING"
    return "APPROVED", None


# --------------------------------------------------------------------------
# 2. batch_blend_metrics
# --------------------------------------------------------------------------
def batch_blend_metrics(feeds):
    """feeds must already be ordered by created_at ASC. Returns
    (feed_moisture_plan_pct, feed_purity_plan_pct, feed_moisture_as_fed_pct)."""
    if not feeds:
        return None, None, None

    total_tons = sum((D(f["tons_fed"]) for f in feeds), Decimal(0))
    if total_tons == 0:
        return None, None, None

    moist_num = sum((D(f["tons_fed"]) * D(f["assay_free_moisture_pct"]) for f in feeds), Decimal(0))
    purity_num = sum((D(f["tons_fed"]) * D(f["assay_purity_pct"]) for f in feeds), Decimal(0))
    plan_moisture = rhu(moist_num / total_tons, 2)
    plan_purity = rhu(purity_num / total_tons, 2)

    acc_tons = Decimal(0)
    acc_moist = Decimal("0.00")
    for f in feeds:
        tons = D(f["tons_fed"])
        new_tons = acc_tons + tons
        acc_moist = rhu(
            (acc_moist * acc_tons + D(f["measured_free_moisture_pct"]) * tons) / new_tons, 2
        )
        acc_tons = new_tons

    return plan_moisture, plan_purity, acc_moist


# --------------------------------------------------------------------------
# 3. stucco_yield_tons
# --------------------------------------------------------------------------
def stucco_yield_tons(feeds, basis):
    """basis is "PLAN" (assay moisture) or "AS_FED" (belt-scale moisture)."""
    field = "assay_free_moisture_pct" if basis == "PLAN" else "measured_free_moisture_pct"
    total = Decimal(0)
    for f in feeds:
        dry = D(f["tons_fed"]) * (Decimal(1) - D(f[field]) / Decimal(100))
        gyp = dry * D(f["assay_purity_pct"]) / Decimal(100)
        inert = dry - gyp
        total += gyp * DIHYDRATE_TO_HEMIHYDRATE_FACTOR + inert * INERT_PASSTHROUGH_FACTOR
    return rhu(total, 3)


# --------------------------------------------------------------------------
# 4. stucco_test_result
# --------------------------------------------------------------------------
def stucco_test_result(combined_water_pct, free_water_pct, set_time_minutes):
    cw = D(combined_water_pct)
    fw = D(free_water_pct)
    st = D(set_time_minutes)
    if cw < COMBINED_WATER_MIN or cw > COMBINED_WATER_MAX:
        return "FAIL"
    if fw > FREE_WATER_FAIL_MAX:
        return "FAIL"
    if st < SET_TIME_FAIL_MIN or st > SET_TIME_FAIL_MAX:
        return "FAIL"
    if fw > FREE_WATER_PASS_MAX or st < SET_TIME_PASS_MIN or st > SET_TIME_PASS_MAX:
        return "MARGINAL"
    return "PASS"


# --------------------------------------------------------------------------
# 5. calciner_aggregate_capacity
# --------------------------------------------------------------------------
def calciner_capacity_exceeded(new_start, new_end, new_rate, others, capacity_tph):
    """Half-open windows. Returns True when any boundary-delimited
    sub-interval of the union carries a load strictly above capacity."""
    overlapping = [
        o
        for o in others
        if o["_feed_window_start"] < new_end and new_start < o["_feed_window_end"]
    ]
    boundaries = {new_start, new_end}
    for o in overlapping:
        for point in (o["_feed_window_start"], o["_feed_window_end"]):
            if new_start <= point <= new_end:
                boundaries.add(point)
    marks = sorted(boundaries)
    for i in range(len(marks) - 1):
        seg_start, seg_end = marks[i], marks[i + 1]
        if seg_start >= seg_end:
            continue
        load = D(new_rate)
        for o in overlapping:
            if o["_feed_window_start"] < seg_end and seg_start < o["_feed_window_end"]:
                load += D(o["feed_rate_tph"])
        if load > D(capacity_tph):
            return True
    return False


# --------------------------------------------------------------------------
# 6. paper_tension_window
# --------------------------------------------------------------------------
def required_paper_tension(spec, line_speed_fpm):
    return rhu(
        D(spec["paper_tension_min_lb"])
        + (D(line_speed_fpm) - PAPER_TENSION_BASE_FPM) * PAPER_TENSION_PER_FPM,
        2,
    )


def paper_tension_ok(spec, line_speed_fpm, paper_tension_lb):
    required = required_paper_tension(spec, line_speed_fpm)
    tension = D(paper_tension_lb)
    return (
        tension >= required and tension <= D(spec["paper_tension_max_lb"]),
        required,
    )


# --------------------------------------------------------------------------
# 7. kiln_energy_and_moisture
# --------------------------------------------------------------------------
def _dryer_efficiency(kiln_dwell_minutes):
    dwell = int(kiln_dwell_minutes)
    if dwell <= 32:
        return D("0.72")
    if dwell <= 45:
        return D("0.81")
    return D("0.86")


def _slurry_water_lb_per_msf(spec):
    return rhu(D(spec["target_board_weight_lb_per_msf"]) * D(spec["slurry_water_stucco_ratio"]), 2)


def projected_exit_moisture(spec, kiln_dwell_minutes):
    slurry = _slurry_water_lb_per_msf(spec)
    eff = _dryer_efficiency(kiln_dwell_minutes)
    drying_capacity = eff * D(kiln_dwell_minutes) * KILN_EVAP_LB_PER_MIN_PER_MSF
    retained = slurry - drying_capacity
    if retained < 0:
        retained = Decimal(0)
    return rhu(retained / D(spec["target_board_weight_lb_per_msf"]) * Decimal(100), 2)


def kiln_profile_feasible(projected_pct, kiln_exit_moisture_target_pct):
    return D(projected_pct) <= D(kiln_exit_moisture_target_pct) + MOISTURE_TOLERANCE_PCT


def kiln_energy(spec, plant, run, effective_planned_msf):
    slurry = _slurry_water_lb_per_msf(spec)
    retained = rhu(
        D(spec["target_board_weight_lb_per_msf"])
        * D(run["kiln_exit_moisture_target_pct"])
        / Decimal(100),
        2,
    )
    evap = slurry - retained
    if evap < 0:
        evap = Decimal(0)

    eff = _dryer_efficiency(run["kiln_dwell_minutes"])
    speed_over = D(run["line_speed_fpm"]) - SPEED_PENALTY_FLOOR_FPM
    if speed_over < 0:
        speed_over = Decimal(0)
    speed_factor = rhu(Decimal(1) + speed_over * SPEED_PENALTY_PER_FPM, 4)
    thickness_multiplier = Decimal(1) + (D(spec["thickness_in"]) - D("0.5")) * (
        THICKNESS_MULTIPLIER_SLOPE
    )
    if thickness_multiplier > THICKNESS_MULTIPLIER_CAP:
        thickness_multiplier = THICKNESS_MULTIPLIER_CAP

    msf = D(effective_planned_msf)
    base_mmbtu = evap * msf * LATENT_HEAT_BTU_PER_LB / eff / Decimal(1000000)
    adder = FIRE_RATED_ADDER_MMBTU_PER_MSF[spec["board_type"]] * msf
    hold = rhu(D(run["kiln_dwell_minutes"]) * KILN_HOLD_MMBTU_PER_MIN, 3)

    mmbtu = rhu(base_mmbtu * thickness_multiplier * speed_factor + adder + hold, 3)
    cost = rhu(mmbtu * D(plant["energy_price_per_mmbtu"]), 2)
    return mmbtu, cost


# --------------------------------------------------------------------------
# 8. run_line_capacity_and_reservation
# --------------------------------------------------------------------------
def select_prior_run(run, candidates):
    """candidates: same line, other id, status IN {SCHEDULED, RUNNING, COMPLETED},
    window_end <= this.window_start. Ranked by window_end DESC, created_at DESC."""
    pool = [
        c
        for c in candidates
        if c["id"] != run["id"]
        and c["line_id"] == run["line_id"]
        and c["status"] in ("SCHEDULED", "RUNNING", "COMPLETED")
        and c["_window_end"] <= run["_window_start"]
    ]
    if not pool:
        return None
    pool.sort(key=lambda c: (c["_window_end"], c["created_at"], c["_seq"]), reverse=True)
    return pool[0]


def changeover_minutes(run, spec, prior, prior_spec):
    if prior is None:
        return COLD_START_MINUTES
    if prior["product_spec_id"] == run["product_spec_id"]:
        minutes = 0
    elif D(prior_spec["thickness_in"]) == D(spec["thickness_in"]) and prior_spec[
        "changeover_family"
    ] == spec["changeover_family"]:
        minutes = 20
    elif D(prior_spec["thickness_in"]) == D(spec["thickness_in"]):
        minutes = 55
    elif prior_spec["changeover_family"] == spec["changeover_family"]:
        minutes = 75
    else:
        minutes = 110
    if spec["fire_rated"] and not prior_spec["fire_rated"]:
        minutes += FIRE_RATED_PURGE_MINUTES
    return minutes


def msf_per_minute(spec, line_speed_fpm):
    return rhu(
        D(line_speed_fpm) * (D(spec["board_width_in"]) / Decimal(12)) / Decimal(1000), 6
    )


def window_minutes(start, end):
    return whole_minutes(start, end)


def stucco_reservation(effective_planned_msf, spec):
    return rhu(D(effective_planned_msf) * D(spec["stucco_lb_per_msf"]) / Decimal(2000), 3)


# --------------------------------------------------------------------------
# 9. board_quality_evaluation
# --------------------------------------------------------------------------
def specimen_result(spec, run, core_hardness_lbf, nail_pull_lbf, flexural_cross_lbf, exit_moisture_pct):
    failing = []
    if D(core_hardness_lbf) < D(spec["core_hardness_min_lbf"]):
        failing.append("CORE_HARDNESS")
    if D(nail_pull_lbf) < D(spec["nail_pull_min_lbf"]):
        failing.append("NAIL_PULL")
    if D(flexural_cross_lbf) < D(spec["flexural_cross_min_lbf"]):
        failing.append("FLEXURAL_CROSS")
    if D(exit_moisture_pct) > D(run["kiln_exit_moisture_target_pct"]) + MOISTURE_TOLERANCE_PCT:
        failing.append("EXIT_MOISTURE")
    return ("FAIL" if failing else "PASS"), failing


def fail_rate_of(failing_specimen_count, specimen_count):
    if not specimen_count:
        return D("0.0000")
    return rhu(D(failing_specimen_count) / D(specimen_count), 4)


def run_quality_state(spec, specimen_count, failing_specimen_count):
    """Caller must have already rejected specimen_count == 0 and < 3."""
    rate = fail_rate_of(failing_specimen_count, specimen_count)
    if spec["fire_rated"] and failing_specimen_count >= 1:
        return "HELD", rate
    if rate == D("0.0000"):
        return "RELEASED", rate
    if rate <= DOWNGRADE_FAIL_RATE_CEILING:
        return "DOWNGRADED", rate
    return "HELD", rate


# --------------------------------------------------------------------------
# 10. plant_production_posture
# --------------------------------------------------------------------------
def production_posture(held_run_count, stucco_available_tons, emergency_active):
    if held_run_count >= FROZEN_HELD_RUN_THRESHOLD or emergency_active:
        return "FROZEN"
    if held_run_count >= 1 or D(stucco_available_tons) < RESTRICTED_STUCCO_FLOOR_TONS:
        return "RESTRICTED"
    return "OPEN"


# --------------------------------------------------------------------------
# 11. outage_seasonality_gate
# --------------------------------------------------------------------------
def seasonality_index_of(window_start):
    return HOUSING_SEASONALITY_INDEX[window_start.month]


def planned_downtime_hours(start, end):
    seconds = D(int((end - start).total_seconds()))
    return rhu(seconds / Decimal(3600), 2)


def outage_gate_allowed(outage):
    if outage["outage_type"] == "EMERGENCY":
        return True
    if int(outage["deferral_count"]) >= MAX_DEFERRALS:
        return True
    return D(outage["seasonality_index"]) <= PLANNED_OUTAGE_INDEX_CEILING


# --------------------------------------------------------------------------
# 12. bundle_load_metrics
# --------------------------------------------------------------------------
def board_msf_each(spec):
    return rhu(
        D(spec["board_length_ft"]) * D(spec["board_width_in"]) / Decimal(12) / Decimal(1000), 6
    )


def bundle_metrics(spec, boards_per_bundle, billable_bundles):
    each = board_msf_each(spec)
    bundle_msf = rhu(D(boards_per_bundle) * each, 4)
    bundle_weight_lb = rhu(
        D(boards_per_bundle) * D(spec["target_board_weight_lb_per_msf"]) * each, 2
    )
    total_msf = rhu(D(billable_bundles) * bundle_msf, 3)
    trailer_weight_lb = rhu(D(billable_bundles) * bundle_weight_lb, 2)
    return each, bundle_msf, bundle_weight_lb, total_msf, trailer_weight_lb


def bundle_config_valid(spec, boards_per_bundle):
    boards = int(boards_per_bundle)
    if boards % 2 != 0:
        return False
    if boards < 2 or boards > int(spec["max_boards_per_bundle"]):
        return False
    return True


# --------------------------------------------------------------------------
# 13. freight_charge
# --------------------------------------------------------------------------
def rate_zone_of(distance_miles):
    distance = D(distance_miles)
    for bound, zone, rate in ZONE_TABLE:
        if distance < bound:
            return zone, rate
    return ZONE_FALLBACK


def freight_charge(
    market, bundle_msf, billable_bundles, trailer_weight_lb=None, backhaul=False, settled=False
):
    _zone, base_rate = rate_zone_of(market["distance_miles"])
    per_bundle_charge = rhu(D(bundle_msf) * D(base_rate), 2)
    subtotal = per_bundle_charge * D(billable_bundles)
    fuel = rhu(subtotal * D(market["fuel_surcharge_pct"]) / Decimal(100), 2)
    if settled:
        over = D(trailer_weight_lb) - TRAILER_TARGET_LB
        if over < 0:
            over = Decimal(0)
        overweight_fee = rhu(over * OVERWEIGHT_USD_PER_LB, 2)
    else:
        overweight_fee = D("0.00")
    credit = D(market["backhaul_credit_usd"]) if (settled and backhaul) else D("0.00")
    charge = rhu(subtotal + fuel + overweight_fee - credit, 2)
    floor = D(market["min_charge_usd"])
    if floor > charge:
        charge = floor
    return charge, overweight_fee
