"""All pinned calculations and the derived-recompute engine."""

from core import (
    DB,
    D,
    add_days,
    add_years,
    fail,
    ifloor,
    iceil,
    floor_to_100,
    fmt_stamp,
    get,
    month_of,
    now,
    parse_dt,
    rows,
    touch,
    year_of,
    q2,
    q4,
)

# ---------------------------------------------------------------- constants

AU_FACTOR = {
    "DAIRY_COW": D("1.4"),
    "BEEF_FEEDER": D("1.0"),
    "SWINE_FINISHING": D("0.4"),
}
AU_FACTOR_LAYER = {"LIQUID": D("0.033"), "DRY": D("0.0125")}
LARGE_AU_THRESHOLD = D(1000)
MEDIUM_AU_THRESHOLD = D(300)

PER_HEAD_ANNUAL_GAL = {
    "DAIRY_COW": D(9000),
    "BEEF_FEEDER": D(3600),
    "SWINE_FINISHING": D(1400),
    "LAYER_HEN": D(30),
}
DILUTION = {"LIQUID": D("1.15"), "DRY": D("1.0")}
NET_PRECIP_FT = D("0.9")
GAL_PER_CUFT = D("7.4805")
DAYS_PER_YEAR = D(365)

SETBACK_TILE_INLET_FT = D(300)
SETBACK_NEAR_WATER_FT = D(200)
SETBACK_BASE_FT = D(100)
NEAR_WATER_FT = D(200)
SETBACK_SLOPE_ADDER_FT = D(100)
SETBACK_SLOPE_THRESHOLD_PCT = D(6)
SQFT_PER_ACRE = D(43560)

P_INDEX_MEDIUM = D(20)
P_INDEX_HIGH = D(50)
P_INDEX_VERY_HIGH = D(100)
SOIL_TEST_VALIDITY_YEARS = 4

CROP_N_PER_UNIT = {
    "CORN_GRAIN": D("1.1"),
    "SOYBEAN": D(0),
    "ALFALFA": D(0),
    "GRASS_HAY": D(45),
}
CROP_P_PER_UNIT = {
    "CORN_GRAIN": D("0.37"),
    "SOYBEAN": D("0.8"),
    "ALFALFA": D(12),
    "GRASS_HAY": D(13),
}
LEGUME_CREDIT_LBS = {
    "SOYBEAN": D(40),
    "ALFALFA": D(100),
    "CORN_GRAIN": D(0),
    "GRASS_HAY": D(0),
    "NONE": D(0),
}
P_INDEX_MULTIPLIER = {
    "LOW": D("4.0"),
    "MEDIUM": D("2.0"),
    "HIGH": D("1.0"),
    "VERY_HIGH": D("0.0"),
}
MANURE_N_LBS_PER_1000GAL = {"DAIRY": D(24), "BEEF": D(32), "SWINE": D(40), "LAYER": D(60)}
MANURE_P2O5_LBS_PER_1000GAL = {"DAIRY": D(10), "BEEF": D(16), "SWINE": D(28), "LAYER": D(45)}
N_AVAILABILITY = {
    "INJECTION": D("0.65"),
    "INCORPORATED_24H": D("0.55"),
    "SURFACE_BROADCAST": D("0.40"),
    "IRRIGATION": D("0.35"),
}
METHOD_SETBACK_MULTIPLIER = {
    "SURFACE_BROADCAST": D("1.0"),
    "IRRIGATION": D("1.5"),
    "INCORPORATED_24H": D("0.5"),
    "INJECTION": D("0.25"),
}

OVERFLOW_FREEBOARD_IN = D(6)
WINTER_SEASONAL_FACTOR = D("1.35")
WINTER_MONTHS = {11, 12, 1, 2, 3}
SEASONAL_TYPES = ("EARTHEN_LAGOON", "STACKING_PAD")
MIN_STORAGE_DAYS = 180

BASE_FEE = {"SMALL": D(150), "MEDIUM": D(400), "LARGE": D(900)}
PER_AU_FEE = D("0.45")
CONSERVATION_TIER_1_FLOOR = D(500)
CONSERVATION_TIER_2_FLOOR = D(1500)
LATE_SURCHARGE_PCT = D("0.25")
COVERAGE_TERM_YEARS = 5
RENEWAL_WINDOW_DAYS = 180
RENEWAL_DUE_DAYS = 90

VARIANCE_TOLERANCE_PCT = D("15.00")

RESTRICTING_COMPLIANCE_STATUSES = ("NOTICE_ISSUED", "CORRECTIVE_ACTION")
OPEN_FINDING_STATUSES = ("NOV_ISSUED", "RESPONSE_SUBMITTED")
OPEN_INCIDENT_STATUSES = ("OPEN", "NOTIFIED", "WRITTEN_SUBMITTED")

MORTALITY_MIN_HEAD = 2
MORTALITY_PCT = D("0.01")
RELEASE_NOTIFICATION_GALLONS = D(1000)
ORAL_NOTIFICATION_HOURS = 24
WRITTEN_REPORT_DAYS = 5

RESPONSE_DAYS = 30
REAPPLICATION_INTERVAL_DAYS = 21
PRECIPITATION_LIMIT_IN = D("0.50")

ANIMAL_GROUP = {
    "DAIRY_COW": "DAIRY",
    "BEEF_FEEDER": "BEEF",
    "SWINE_FINISHING": "SWINE",
    "LAYER_HEN": "LAYER",
}

ACTIVE_EVENT_STATUSES = ("RECORDED", "VERIFIED")
SETTLED_TRANSFER_STATUSES = ("ACKNOWLEDGED", "COMPLETED")


# ---------------------------------------------------------------- helpers


def set_fields(table, row, changes):
    """Explicit mutation: refresh updated_at/version only when something moved."""
    dirty = False
    for k, v in changes.items():
        if row.get(k) != v:
            row[k] = v
            dirty = True
    if dirty:
        touch(table, row)
    return dirty


def set_derived(table, row, changes):
    """Derived recomputation: never bumps version and never moves updated_at."""
    dirty = False
    for k, v in changes.items():
        if row.get(k) != v:
            row[k] = v
            dirty = True
    return dirty


def group_of(op):
    return ANIMAL_GROUP[op["animal_type"]]


# ---------------------------------------------------------------- operation


def operation_animal_units_and_class(op):
    at = op["animal_type"]
    if at == "LAYER_HEN":
        factor = AU_FACTOR_LAYER[op["manure_handling"]]
    else:
        factor = AU_FACTOR[at]
    au = q2(D(op["head_count"]) * factor)
    if au >= LARGE_AU_THRESHOLD:
        size = "LARGE"
    elif au >= MEDIUM_AU_THRESHOLD:
        size = "MEDIUM"
    else:
        size = "SMALL"
    dp = op["discharge_potential"]
    if size == "LARGE":
        req = True
    elif size == "MEDIUM":
        req = dp in ("STORMWATER_ONLY", "CONTINUOUS")
    else:
        req = dp == "CONTINUOUS"
    return {"animal_units": au, "size_class": size, "permit_required": req}


def operation_design_production(op):
    per_head = PER_HEAD_ANNUAL_GAL[op["animal_type"]]
    dil = DILUTION[op["manure_handling"]]
    lot = q2(D(op["open_lot_area_sqft"]) * NET_PRECIP_FT * GAL_PER_CUFT)
    annual = q2(D(op["head_count"]) * per_head * dil + lot)
    daily = q2(annual / DAYS_PER_YEAR)
    return {"design_annual_manure_gallons": annual, "daily_production_gallons": daily}


def _plan_ids_of(op_id):
    return {p["id"] for p in DB["plans"].values() if p.get("operation_id") == op_id}


def events_of_operation(op_id, year=None, active_only=True):
    plan_ids = _plan_ids_of(op_id)
    out = []
    for e in rows("events"):
        if e.get("plan_id") not in plan_ids:
            continue
        if active_only and e["event_status"] not in ACTIVE_EVENT_STATUSES:
            continue
        if year is not None and year_of(parse_dt(e["applied_on"])) != year:
            continue
        out.append(e)
    return out


def transfers_of_operation(op_id, year=None, settled_only=True):
    out = []
    for t in rows("transfers"):
        if t.get("operation_id") != op_id:
            continue
        if settled_only and t["transfer_status"] not in SETTLED_TRANSFER_STATUSES:
            continue
        if year is not None and year_of(parse_dt(t["transferred_on"])) != year:
            continue
        out.append(t)
    return out


def records_basis(op_id, year):
    land = D(0)
    for e in events_of_operation(op_id, year):
        land += D(e["gallons_applied"])
    tr = D(0)
    for t in transfers_of_operation(op_id, year):
        tr += D(t["gallons_transferred"])
    return q2(land), q2(tr)


def nutrient_rollup(op_id, year):
    n = D(0)
    p = D(0)
    for e in events_of_operation(op_id, year):
        n += D(e["n_applied_lbs"])
        p += D(e["p2o5_applied_lbs"])
    return q2(n), q2(p)


# ---------------------------------------------------------------- field / soil


def field_setback_and_net_acres(f):
    if f["has_tile_inlet"]:
        base = SETBACK_TILE_INLET_FT
    elif D(f["distance_to_water_ft"]) <= NEAR_WATER_FT:
        base = SETBACK_NEAR_WATER_FT
    else:
        base = SETBACK_BASE_FT
    adder = (
        SETBACK_SLOPE_ADDER_FT
        if D(f["slope_pct"]) > SETBACK_SLOPE_THRESHOLD_PCT
        else D(0)
    )
    setback = base + adder
    excluded = q2(setback * D(f["water_frontage_ft"]) / SQFT_PER_ACRE)
    net = q2(D(f["total_acres"]) - excluded)
    return {
        "required_setback_ft": q2(setback),
        "excluded_acres": excluded,
        "net_applicable_acres": net,
    }


def soil_test_valid(st):
    return now() < add_years(parse_dt(st["sampled_on"]), SOIL_TEST_VALIDITY_YEARS)


def soil_test_p_index(st, field):
    p = q2(D(st["soil_test_p_ppm"]) * (D(1) + D(field["slope_pct"]) / D(100)))
    if p >= P_INDEX_VERY_HIGH:
        cat = "VERY_HIGH"
    elif p >= P_INDEX_HIGH:
        cat = "HIGH"
    elif p >= P_INDEX_MEDIUM:
        cat = "MEDIUM"
    else:
        cat = "LOW"
    return {"p_index": p, "p_index_category": cat, "is_valid": soil_test_valid(st)}


# ---------------------------------------------------------------- budget


def budget_allowable_rate(op, field, soil, crop, yield_goal, previous_crop, method):
    grp = group_of(op)
    yg = D(yield_goal)
    crop_n = q2(CROP_N_PER_UNIT[crop] * yg)
    legume = q2(LEGUME_CREDIT_LBS[previous_crop])
    adjusted = q2(crop_n - legume)
    if adjusted < 0:
        adjusted = D("0.00")
    crop_p = q2(CROP_P_PER_UNIT[crop] * yg)
    p_allow = q2(crop_p * P_INDEX_MULTIPLIER[soil["p_index_category"]])
    avail_n = q2(MANURE_N_LBS_PER_1000GAL[grp] * N_AVAILABILITY[method])
    if avail_n == 0:
        n_rate = 0
    else:
        n_rate = floor_to_100(adjusted / avail_n * D(1000))
    p2o5 = MANURE_P2O5_LBS_PER_1000GAL[grp]
    p_rate = floor_to_100(p_allow / p2o5 * D(1000))
    rate = min(n_rate, p_rate)
    basis = "NITROGEN" if n_rate <= p_rate else "PHOSPHORUS"
    total = ifloor(D(rate) * D(field["net_applicable_acres"]))
    return {
        "crop_n_need_lbs": crop_n,
        "legume_credit_lbs": legume,
        "adjusted_n_need_lbs": adjusted,
        "crop_p_removal_lbs": crop_p,
        "p_allowance_lbs": p_allow,
        "allowable_n_rate_gal_per_acre": q2(n_rate),
        "allowable_p_rate_gal_per_acre": q2(p_rate),
        "binding_basis": basis,
        "allowable_rate_gal_per_acre": q2(rate),
        "allowable_total_gallons": total,
    }


# ---------------------------------------------------------------- nutrient load


def application_load(op, gallons, method):
    grp = group_of(op)
    g = D(gallons)
    n = q2(g / D(1000) * MANURE_N_LBS_PER_1000GAL[grp] * N_AVAILABILITY[method])
    p = q2(g / D(1000) * MANURE_P2O5_LBS_PER_1000GAL[grp])
    return n, p


def transfer_load(op, gallons):
    grp = group_of(op)
    g = D(gallons)
    n = q2(g / D(1000) * MANURE_N_LBS_PER_1000GAL[grp])
    p = q2(g / D(1000) * MANURE_P2O5_LBS_PER_1000GAL[grp])
    return n, p


# ---------------------------------------------------------------- storage


def storage_geometry(st):
    design = q2(D(st["surface_area_sqft"]) * D(st["total_depth_in"]) * GAL_PER_CUFT / D(12))
    reserve = q2(
        D(st["surface_area_sqft"]) * D(st["required_freeboard_in"]) * GAL_PER_CUFT / D(12)
    )
    return {
        "design_capacity_gallons": design,
        "freeboard_reserve_gallons": reserve,
        "operating_capacity_gallons": q2(design - reserve),
    }


def measured_volume(st, measured_freeboard_in):
    liquid = D(st["total_depth_in"]) - D(measured_freeboard_in)
    return q2(D(st["surface_area_sqft"]) * liquid * GAL_PER_CUFT / D(12))


def seasonal_factor_for(structure_type):
    if structure_type in SEASONAL_TYPES and month_of(now()) in WINTER_MONTHS:
        return WINTER_SEASONAL_FACTOR
    return D("1.0")


def effective_daily(op, factor):
    return q4(D(op["daily_production_gallons"]) * factor)


def _floor_days(numerator, eff):
    if eff <= 0:
        return 0
    n = D(numerator)
    if n < 0:
        n = D(0)
    return ifloor(n / eff)


def storages_of(op_id):
    return [s for s in rows("storages") if s.get("operation_id") == op_id]


def operation_seasonal_factor(op_id):
    for s in storages_of(op_id):
        if s["structure_type"] in SEASONAL_TYPES:
            return seasonal_factor_for(s["structure_type"])
    return D("1.0")


def design_storage_days(op):
    total = D(0)
    for s in storages_of(op["id"]):
        total += D(s["operating_capacity_gallons"])
    eff = effective_daily(op, operation_seasonal_factor(op["id"]))
    return _floor_days(total, eff)


def recompute_storage(st, op):
    changes = {}
    changes.update(storage_geometry(st))
    outflow = D(0)
    committed = D(0)
    for e in rows("events"):
        if e.get("storage_id") == st["id"] and e["event_status"] in ACTIVE_EVENT_STATUSES:
            outflow += D(e["gallons_applied"])
    for t in rows("transfers"):
        if t.get("storage_id") != st["id"]:
            continue
        if t["transfer_status"] in SETTLED_TRANSFER_STATUSES:
            outflow += D(t["gallons_transferred"])
        elif t["transfer_status"] == "INITIATED":
            committed += D(t["gallons_transferred"])
    intake = D(st.get("cumulative_intake_gallons", 0))
    precip = D(st.get("precipitation_adjustment_gallons", 0))
    current = q2(intake + precip - outflow)
    available = q2(D(changes["operating_capacity_gallons"]) - current - q2(committed))
    changes["cumulative_outflow_gallons"] = q2(outflow)
    changes["committed_outflow_gallons"] = q2(committed)
    changes["current_volume_gallons"] = current
    changes["available_capacity_gallons"] = available
    eff = effective_daily(op, seasonal_factor_for(st["structure_type"]))
    changes["days_of_storage_available"] = _floor_days(available, eff)
    last = None
    for insp in rows("storage_inspections"):
        if insp.get("storage_id") != st["id"]:
            continue
        d = parse_dt(insp["inspected_on"])
        if last is None or d > last:
            last = d
    changes["last_inspected_on"] = (
        None if last is None else insp_fmt(last)
    )
    set_derived("storages", st, changes)


def insp_fmt(dt):
    from core import fmt_dt

    return fmt_dt(dt)


def latest_inspection(storage_id):
    best = None
    for insp in rows("storage_inspections"):
        if insp.get("storage_id") != storage_id:
            continue
        key = (parse_dt(insp["inspected_on"]), insp["created_at"], insp["_seq"])
        if best is None or key > best[0]:
            best = (key, insp)
    return None if best is None else best[1]


# ---------------------------------------------------------------- permit


def permit_renewal_fee(permit, op):
    gross = q2(BASE_FEE[op["size_class"]] + D(op["animal_units"]) * PER_AU_FEE)
    if not op.get("has_conservation_plan"):
        pct = D("0.00")
    elif gross < CONSERVATION_TIER_1_FLOOR:
        pct = D("0.00")
    elif gross < CONSERVATION_TIER_2_FLOOR:
        pct = D("0.05")
    else:
        pct = D("0.10")
    amount = q2(gross * pct)
    net = q2(gross - amount)
    late = q2(net * LATE_SURCHARGE_PCT) if permit.get("is_late_renewal") else D("0.00")
    total = q2(net + late)
    return {
        "gross_fee": gross,
        "conservation_discount_pct": pct,
        "conservation_discount_amount": amount,
        "net_fee": net,
        "late_surcharge_amount": late,
        "total_due": total,
    }


def stamp_coverage_dates(permit, effective_on):
    from core import fmt_dt

    exp = add_years(effective_on, COVERAGE_TERM_YEARS)
    permit["effective_on"] = fmt_dt(effective_on)
    permit["expiration_on"] = fmt_dt(exp)
    permit["renewal_window_opens_on"] = fmt_dt(add_days(exp, -RENEWAL_WINDOW_DAYS))
    permit["renewal_due_on"] = fmt_dt(add_days(exp, -RENEWAL_DUE_DAYS))


# ---------------------------------------------------------------- annual report


def annual_report_mass_balance(rep, op):
    land, tr = records_basis(rep["operation_id"], rep["report_year"])
    total = q2(land + tr + (D(rep["ending_storage_gallons"]) - D(rep["beginning_storage_gallons"])))
    expected = D(op["design_annual_manure_gallons"])
    if expected == 0:
        variance = D("0.00")
    else:
        variance = q2((total - expected) / expected * D(100))
    cls = "WITHIN_TOLERANCE" if abs(variance) <= VARIANCE_TOLERANCE_PCT else "EXCEEDS_TOLERANCE"
    n, p = nutrient_rollup(rep["operation_id"], rep["report_year"])
    return {
        "recorded_land_applied_gallons": land,
        "recorded_transferred_gallons": tr,
        "recorded_total_gallons": total,
        "mass_balance_expected_gallons": q2(expected),
        "variance_pct": variance,
        "variance_classification": cls,
        "total_n_applied_lbs": n,
        "total_p2o5_applied_lbs": p,
    }


# ---------------------------------------------------------------- incident


def incident_notification_deadlines(inc, op):
    from core import fmt_dt

    discovered = parse_dt(inc["discovered_at"])
    if inc["incident_type"] in ("DISCHARGE", "SPILL"):
        required = bool(inc.get("reached_water")) or D(
            inc.get("released_gallons", 0)
        ) >= RELEASE_NOTIFICATION_GALLONS
    else:
        threshold = max(MORTALITY_MIN_HEAD, iceil(MORTALITY_PCT * D(op["head_count"])))
        required = int(inc.get("mortality_head_count", 0) or 0) >= threshold
    if required:
        oral = fmt_dt(discovered.replace() + _hours(ORAL_NOTIFICATION_HOURS))
        written = fmt_dt(add_days(discovered, WRITTEN_REPORT_DAYS))
    else:
        oral = None
        written = None
    return {
        "requires_oral_notification": required,
        "oral_notification_deadline_at": oral,
        "written_report_deadline_at": written,
    }


def _hours(n):
    from datetime import timedelta

    return timedelta(hours=n)


# ---------------------------------------------------------------- budgets / fields


def recompute_budget(b):
    applied = D(0)
    for e in rows("events"):
        if e.get("budget_id") == b["id"] and e["event_status"] in ACTIVE_EVENT_STATUSES:
            applied += D(e["gallons_applied"])
    total = D(b["allowable_total_gallons"])
    set_derived(
        "budgets",
        b,
        {
            "applied_gallons_to_date": q2(applied),
            "remaining_gallons": q2(total - applied),
        },
    )


def recompute_field(f):
    from core import fmt_dt

    best = None
    for e in rows("events"):
        if e["event_status"] not in ACTIVE_EVENT_STATUSES:
            continue
        b = get("budgets", e.get("budget_id"))
        if b is None or b.get("field_id") != f["id"]:
            continue
        d = parse_dt(e["applied_on"])
        if best is None or d > best:
            best = d
    set_derived("fields", f, {"last_application_on": None if best is None else fmt_dt(best)})


def field_of_budget(b):
    return get("fields", b.get("field_id"))


# ---------------------------------------------------------------- posture


def _posture_of(op):
    op_id = op["id"]
    findings = 0
    for i in DB["inspections"].values():
        if i.get("operation_id") == op_id and i["inspection_status"] in OPEN_FINDING_STATUSES:
            findings += 1
    incidents = 0
    for inc in DB["incidents"].values():
        if (
            inc.get("operation_id") == op_id
            and inc["incident_type"] in ("DISCHARGE", "SPILL")
            and inc["incident_status"] in OPEN_INCIDENT_STATUSES
        ):
            incidents += 1
    sts = storages_of(op_id)
    overflow = any(s["storage_status"] == "OVERFLOW_IMMINENT" for s in sts)
    alert = any(s["storage_status"] == "FREEBOARD_ALERT" for s in sts)
    notice = any(
        p.get("operation_id") == op_id
        and p["compliance_status"] in RESTRICTING_COMPLIANCE_STATUSES
        for p in DB["permits"].values()
    )
    if incidents >= 1 or overflow:
        posture = "SUSPENDED"
    elif findings >= 1 or alert or notice:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return posture, findings, incidents


def apply_posture_and_cascade(op):
    """Recompute posture, then run the two propagation steps. Idempotent."""
    posture, findings, incidents = _posture_of(op)
    set_derived(
        "operations",
        op,
        {
            "compliance_posture": posture,
            "open_finding_count": findings,
            "open_discharge_incident_count": incidents,
        },
    )
    if posture not in ("RESTRICTED", "SUSPENDED"):
        return
    op_id = op["id"]
    # step 1: approved plans -> REVISION_REQUIRED, locking their budgets
    for p in rows("plans"):
        if p.get("operation_id") != op_id or p["plan_status"] != "APPROVED":
            continue
        set_fields(
            "plans",
            p,
            {
                "plan_status": "REVISION_REQUIRED",
                "revision_count": int(p.get("revision_count", 0)) + 1,
            },
        )
        lock_budgets(p["id"], "LOCKED")
    # step 2: INITIATED transfers -> SUSPENDED, ascending created_at
    pending = [
        t
        for t in DB["transfers"].values()
        if t.get("operation_id") == op_id and t["transfer_status"] == "INITIATED"
    ]
    pending.sort(key=lambda t: (t["created_at"], t["_seq"]))
    touched = set()
    for t in pending:
        set_fields("transfers", t, {"transfer_status": "SUSPENDED"})
        touched.add(t.get("storage_id"))
    for sid in touched:
        st = get("storages", sid)
        if st is not None:
            recompute_storage(st, op)


def lock_budgets(plan_id, status):
    for b in rows("budgets"):
        if b.get("plan_id") == plan_id:
            set_fields("budgets", b, {"budget_status": status})


# ---------------------------------------------------------------- full recompute


def recompute_operation(op, year=None):
    """Recompute every derived value hanging off one operation, then cascade."""
    op_id = op["id"]
    changes = {}
    changes.update(operation_animal_units_and_class(op))
    changes.update(operation_design_production(op))
    set_derived("operations", op, changes)

    for st in storages_of(op_id):
        recompute_storage(st, op)

    plan_ids = _plan_ids_of(op_id)
    for b in rows("budgets"):
        if b.get("plan_id") in plan_ids:
            recompute_budget(b)
    for f in rows("fields"):
        if f.get("operation_id") == op_id:
            recompute_field(f)

    y = year_of(now()) if year is None else year
    land, tr = records_basis(op_id, y)
    set_derived(
        "operations",
        op,
        {
            "recorded_annual_manure_gallons": q2(land + tr),
            "design_storage_days": design_storage_days(op),
        },
    )
    apply_posture_and_cascade(op)
    # the cascade may have freed committed volume; refresh the aggregates once more
    for st in storages_of(op_id):
        recompute_storage(st, op)
    set_derived("operations", op, {"design_storage_days": design_storage_days(op)})


def recompute_all():
    for op in rows("operations"):
        recompute_operation(op)


def hauler_status_of(h):
    return "ACTIVE" if now() <= parse_dt(h["license_expires_on"]) else "LAPSED"


def refresh_hauler(h):
    set_derived("haulers", h, {"hauler_status": hauler_status_of(h)})


def refresh_soil_test(st):
    st["is_valid"] = soil_test_valid(st)
