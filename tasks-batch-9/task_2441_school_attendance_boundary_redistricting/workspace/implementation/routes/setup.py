"""Studies, schools, planning areas, adjacency graph and the housing pipeline."""

from flask import Blueprint, request

import calc
import core
from core import (
    ALL_ROLES,
    LEVELS,
    PROGRAM_TYPES,
    READ_ROLES_INTERNAL,
    READ_ROLES_PUBLIC,
    SCHOOL_STATUSES,
    UNIT_TYPES,
    adjacencies_of_study,
    areas_of_study,
    as_bool,
    as_enum,
    as_int,
    as_num,
    as_pct,
    as_str,
    as_str_array,
    authenticate,
    bool_filter,
    body_json,
    db,
    dec,
    developments_of_area,
    fail,
    get_area,
    get_development,
    get_school,
    get_study,
    iso3,
    need,
    new_record,
    now,
    ordered,
    paginate,
    parse_dt,
    present,
    pub,
    recompute_school_capacity,
    recompute_school_enrollment,
    recompute_study_rollups,
    recompute_study_values,
    respond,
    round_half_up,
    runs_of_study,
    scenarios_of_study,
    schools_of_study,
    set_study_status,
    sort_key,
    study_serializer,
    touch,
)

bp = Blueprint("setup", __name__)


def pre_resolve(getter, value):
    """Existence (precedence 4) runs before schema (precedence 5), so only
    well-formed identifiers are resolved here; anything else falls through to the
    schema check."""
    if isinstance(value, str) and value:
        return getter(value)
    return None


def dev_serializer(rec):
    return pub(rec)


# ==========================================================================
# Boundary studies
# ==========================================================================
@bp.post("/studies")
def create_study():
    authenticate(["DistrictPlanner"])
    body = body_json()
    name = as_str(need(body, "name"), "name")
    district_name = as_str(need(body, "district_name"), "district_name")
    target_school_year = as_int(need(body, "target_school_year"), "target_school_year", minimum=2026)
    horizon_years = 5
    if present(body, "horizon_years"):
        horizon_years = as_int(body["horizon_years"], "horizon_years", minimum=1, maximum=10)
    low = as_pct(need(body, "capacity_target_low_pct"), "capacity_target_low_pct")
    high = as_pct(need(body, "capacity_target_high_pct"), "capacity_target_high_pct")
    low = round_half_up(low, 2)
    high = round_half_up(high, 2)
    if low <= 0:
        fail("ERR_INVALID_REQUEST", "capacity_target_low_pct must be greater than 0.")
    if low >= high:
        fail("ERR_INVALID_REQUEST", "capacity_target_low_pct must be strictly below capacity_target_high_pct.")
    if high >= calc.CRITICAL_UTILIZATION_PCT:
        fail("ERR_INVALID_REQUEST", "capacity_target_high_pct must be strictly below 110.00.")
    portables = False
    if present(body, "portables_count_toward_capacity"):
        portables = as_bool(body["portables_count_toward_capacity"], "portables_count_toward_capacity")
    required_programs = []
    if present(body, "required_program_types"):
        required_programs = as_str_array(body["required_program_types"], "required_program_types", PROGRAM_TYPES)

    study = new_record()
    study.update({
        "name": name,
        "district_name": district_name,
        "target_school_year": target_school_year,
        "horizon_years": horizon_years,
        "capacity_target_low_pct": float(low),
        "capacity_target_high_pct": float(high),
        "portables_count_toward_capacity": portables,
        "required_program_types": required_programs,
        "status": "SETUP",
        "comment_intake_open": False,
        "data_locked_at": None,
        "resident_student_total": 0,
        "enrolled_of_record_total": 0,
        "projection_stale": False,
    })
    db.studies[study["id"]] = study
    return respond(study_serializer(study), 201)


@bp.get("/studies/<study_id>")
def read_study(study_id):
    authenticate(READ_ROLES_PUBLIC)
    study = get_study(study_id)
    return respond(study_serializer(study))


@bp.post("/studies/<study_id>/lock-data")
def lock_data(study_id):
    authenticate(["DistrictPlanner"])
    study = get_study(study_id)
    if study["status"] != "SETUP":
        fail("ERR_STUDY_PHASE_INVALID")

    schools = schools_of_study(study["id"])
    active = [s for s in schools if s["status"] == "ACTIVE"]
    areas = areas_of_study(study["id"])
    if len(active) < calc.MIN_ACTIVE_SCHOOLS or len(areas) < calc.MIN_PLANNING_AREAS:
        fail("ERR_STUDY_SETUP_INCOMPLETE")
    adjacency_sources = {row["area_id"] for row in adjacencies_of_study(study["id"])}
    for area in areas:
        if area["id"] not in adjacency_sources:
            fail("ERR_STUDY_SETUP_INCOMPLETE")
        expected = [s["id"] for s in active if s["level"] == area["grade_band"]]
        listed = [entry["school_id"] for entry in area["travel_options"]]
        for school_id in expected:
            if listed.count(school_id) != 1:  # no missing pair, no duplicate pair
                fail("ERR_STUDY_SETUP_INCOMPLETE")

    study["data_locked_at"] = iso3(now())
    study["status"] = "DATA_LOCKED"
    for school in schools:  # School.created_at ASC
        recompute_school_enrollment(school)
    recompute_study_values(study)
    touch(study)
    return respond(study_serializer(study))


@bp.post("/studies/<study_id>/open-engagement")
def open_engagement(study_id):
    authenticate(["EngagementCoordinator"])
    study = get_study(study_id)
    if study["status"] != "SCENARIO_DEVELOPMENT":
        fail("ERR_STUDY_PHASE_INVALID")
    if not any(s["status"] == "UNDER_REVIEW" for s in scenarios_of_study(study["id"])):
        fail("ERR_NO_SCENARIO_UNDER_REVIEW")
    study["status"] = "ENGAGEMENT"
    recompute_study_values(study)
    touch(study)
    return respond(study_serializer(study))


# ==========================================================================
# Schools
# ==========================================================================
@bp.post("/studies/<study_id>/schools")
def create_school(study_id):
    authenticate(["DistrictPlanner"])
    study = get_study(study_id)
    body = body_json()
    name = as_str(need(body, "name"), "name")
    level = as_enum(need(body, "level"), "level", LEVELS)
    core_seats = as_int(need(body, "core_capacity_seats"), "core_capacity_seats", minimum=1)
    portable_seats = 0
    if present(body, "portable_capacity_seats"):
        portable_seats = as_int(body["portable_capacity_seats"], "portable_capacity_seats", minimum=0)
    program_types = []
    if present(body, "program_types"):
        program_types = as_str_array(body["program_types"], "program_types", PROGRAM_TYPES)
    status = "ACTIVE"
    if present(body, "status"):
        status = as_enum(body["status"], "status", SCHOOL_STATUSES)

    if study["status"] != "SETUP":
        fail("ERR_STUDY_DATA_LOCKED")
    for existing in schools_of_study(study["id"]):
        if existing["name"] == name:
            fail("ERR_DUPLICATE_NAME")

    school = new_record()
    school.update({
        "study_id": study["id"],
        "name": name,
        "level": level,
        "core_capacity_seats": core_seats,
        "portable_capacity_seats": portable_seats,
        "program_types": program_types,
        "status": status,
        "effective_capacity_seats": core_seats + (portable_seats if study["portables_count_toward_capacity"] else 0),
        "enrolled_students_of_record": 0,
    })
    db.schools[school["id"]] = school
    return respond(pub(school), 201)


@bp.get("/studies/<study_id>/schools")
def list_schools(study_id):
    authenticate(READ_ROLES_PUBLIC)
    study = get_study(study_id)
    rows = schools_of_study(study["id"])
    level = request.args.get("level")
    if level:
        rows = [r for r in rows if r["level"] == level]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, pub)


@bp.get("/schools/<school_id>")
def read_school(school_id):
    authenticate(READ_ROLES_PUBLIC)
    return respond(pub(get_school(school_id)))


@bp.patch("/schools/<school_id>")
def patch_school(school_id):
    authenticate(["DistrictPlanner"])
    school = get_school(school_id)
    body = body_json()
    updates = {}
    if present(body, "core_capacity_seats"):
        updates["core_capacity_seats"] = as_int(body["core_capacity_seats"], "core_capacity_seats", minimum=1)
    if present(body, "portable_capacity_seats"):
        updates["portable_capacity_seats"] = as_int(body["portable_capacity_seats"], "portable_capacity_seats", minimum=0)
    if present(body, "program_types"):
        updates["program_types"] = as_str_array(body["program_types"], "program_types", PROGRAM_TYPES)
    if present(body, "status"):
        updates["status"] = as_enum(body["status"], "status", SCHOOL_STATUSES)
    school.update(updates)
    study = db.studies[school["study_id"]]
    recompute_school_capacity(school, study)
    touch(school)
    return respond(pub(school))


# ==========================================================================
# Planning areas
# ==========================================================================
def _validate_travel_options(raw, area_grade_band, study):
    entries = []
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_REQUEST", "travel_options must be a non-empty array.")
    for item in raw:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "Each travel_options entry must be an object.")
        for key in ("school_id", "walk_distance_miles", "bus_minutes", "has_safe_route"):
            if key not in item or item[key] is None:
                fail("ERR_INVALID_REQUEST", "travel_options entry is missing '%s'." % key)
        entries.append({
            "school_id": as_str(item["school_id"], "school_id"),
            "walk_distance_miles": float(as_num(item["walk_distance_miles"], "walk_distance_miles", minimum=0)),
            "bus_minutes": float(as_num(item["bus_minutes"], "bus_minutes", minimum=1)),
            "has_safe_route": as_bool(item["has_safe_route"], "has_safe_route"),
        })
    for entry in entries:
        if float(entry["bus_minutes"]).is_integer():
            entry["bus_minutes"] = int(entry["bus_minutes"])
    return entries


@bp.post("/planning-areas")
def create_area():
    authenticate(["DistrictPlanner"])
    body = body_json()
    study = pre_resolve(get_study, body.get("study_id"))
    school_of_record = pre_resolve(get_school, body.get("current_school_id"))
    raw_options = body.get("travel_options")
    if isinstance(raw_options, list):
        for item in raw_options:
            if isinstance(item, dict) and isinstance(item.get("school_id"), str) and item["school_id"]:
                get_school(item["school_id"])

    study = get_study(as_str(need(body, "study_id"), "study_id"))
    area_code = as_str(need(body, "area_code"), "area_code")
    grade_band = as_enum(need(body, "grade_band"), "grade_band", LEVELS)
    school_of_record = get_school(as_str(need(body, "current_school_id"), "current_school_id"))
    resident = as_int(need(body, "resident_student_count"), "resident_student_count", minimum=0)
    frl = as_int(need(body, "frl_student_count"), "frl_student_count", minimum=0, maximum=resident)
    ell = as_int(need(body, "ell_student_count"), "ell_student_count", minimum=0, maximum=resident)
    income = as_int(need(body, "median_household_income_usd"), "median_household_income_usd", minimum=0)
    absorption_cap = 250
    if present(body, "annual_absorption_cap_units"):
        absorption_cap = as_int(body["annual_absorption_cap_units"], "annual_absorption_cap_units", minimum=1)
    options = _validate_travel_options(need(body, "travel_options"), grade_band, study)

    if study["status"] != "SETUP":
        fail("ERR_STUDY_DATA_LOCKED")

    # Referential business rules: level mismatch precedes cross-study (PRD 2.10 #16).
    for entry in options:
        if db.schools[entry["school_id"]]["level"] != grade_band:
            fail("ERR_SCHOOL_LEVEL_MISMATCH")
    if school_of_record["study_id"] != study["id"]:
        fail("ERR_CROSS_STUDY_REFERENCE")
    for entry in options:
        if db.schools[entry["school_id"]]["study_id"] != study["id"]:
            fail("ERR_CROSS_STUDY_REFERENCE")

    for existing in areas_of_study(study["id"]):
        if existing["area_code"] == area_code:
            fail("ERR_DUPLICATE_NAME")

    area = new_record()
    area.update({
        "study_id": study["id"],
        "area_code": area_code,
        "grade_band": grade_band,
        "current_school_id": school_of_record["id"],
        "previous_school_id": None,
        "resident_student_count": resident,
        "frl_student_count": frl,
        "ell_student_count": ell,
        "median_household_income_usd": income,
        "annual_absorption_cap_units": absorption_cap,
        "travel_options": options,
    })
    db.areas[area["id"]] = area
    recompute_school_enrollment(school_of_record)
    recompute_study_rollups(study)
    return respond(pub(area), 201)


@bp.get("/planning-areas")
def list_areas():
    authenticate(READ_ROLES_PUBLIC)
    rows = ordered(list(db.areas.values()))
    for key in ("study_id", "current_school_id", "previous_school_id", "grade_band"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, pub)


@bp.get("/planning-areas/<area_id>")
def read_area(area_id):
    authenticate(READ_ROLES_PUBLIC)
    return respond(pub(get_area(area_id)))


# ==========================================================================
# Area adjacencies
# ==========================================================================
@bp.post("/area-adjacencies")
def create_adjacency():
    authenticate(["DistrictPlanner"])
    body = body_json()
    pre_resolve(get_area, body.get("area_id"))
    pre_resolve(get_area, body.get("neighbor_area_id"))

    area = get_area(as_str(need(body, "area_id"), "area_id"))
    neighbour = get_area(as_str(need(body, "neighbor_area_id"), "neighbor_area_id"))
    length = as_int(need(body, "shared_boundary_length_ft"), "shared_boundary_length_ft", minimum=1)

    study = db.studies[area["study_id"]]
    if study["status"] != "SETUP":
        fail("ERR_STUDY_DATA_LOCKED")
    if area["id"] == neighbour["id"]:
        fail("ERR_SELF_ADJACENCY")
    if area["study_id"] != neighbour["study_id"]:
        fail("ERR_CROSS_STUDY_REFERENCE")
    for row in db.adjacencies.values():
        pair = {row["area_id"], row["neighbor_area_id"]}
        if pair == {area["id"], neighbour["id"]}:
            fail("ERR_DUPLICATE_ADJACENCY")

    primary = new_record(mutable=False)
    primary.update({
        "area_id": area["id"],
        "neighbor_area_id": neighbour["id"],
        "shared_boundary_length_ft": length,
        "is_reciprocal": False,
    })
    db.adjacencies[primary["id"]] = primary
    mirror = new_record(mutable=False)
    mirror.update({
        "area_id": neighbour["id"],
        "neighbor_area_id": area["id"],
        "shared_boundary_length_ft": length,
        "is_reciprocal": True,
    })
    db.adjacencies[mirror["id"]] = mirror
    return respond(pub(primary), 201)


@bp.get("/planning-areas/<area_id>/adjacencies")
def list_adjacencies(area_id):
    authenticate(READ_ROLES_INTERNAL)
    area = get_area(area_id)
    rows = ordered([
        r for r in db.adjacencies.values()
        if r["area_id"] == area["id"] or r["neighbor_area_id"] == area["id"]
    ])
    reciprocal = bool_filter("is_reciprocal")
    if reciprocal is not None:
        rows = [r for r in rows if r["is_reciprocal"] is reciprocal]
    return paginate(rows, pub)


# ==========================================================================
# Housing developments
# ==========================================================================
@bp.post("/planning-areas/<area_id>/housing-developments")
def create_development(area_id):
    authenticate(["DistrictPlanner"])
    area = get_area(area_id)
    body = body_json()
    name = as_str(need(body, "name"), "name")
    unit_type = as_enum(need(body, "unit_type"), "unit_type", UNIT_TYPES)
    total_units = as_int(need(body, "total_units"), "total_units", minimum=1)
    first_occupancy = parse_dt(need(body, "first_occupancy_date"))
    buildout_months = as_int(need(body, "buildout_months"), "buildout_months", minimum=1)
    yield_override = None
    if present(body, "student_yield_override"):
        yield_override = round_half_up(
            as_num(body["student_yield_override"], "student_yield_override", minimum=0, maximum=2), 4
        )

    study = db.studies[area["study_id"]]
    if study["status"] == "CLOSED":
        fail("ERR_STUDY_PHASE_INVALID")

    candidates = []
    for existing in developments_of_area(area["id"]):
        if existing["entitlement_status"] == "WITHDRAWN":
            continue
        candidates.append({
            "first_occupancy_dt": existing["_first_occupancy_dt"],
            "buildout_months": existing["buildout_months"],
            "total_units": existing["total_units"],
        })
    candidates.append({
        "first_occupancy_dt": first_occupancy,
        "buildout_months": buildout_months,
        "total_units": total_units,
    })
    peak = calc.absorption_peak(candidates)
    if peak > dec(area["annual_absorption_cap_units"]):
        fail("ERR_AREA_ABSORPTION_EXCEEDED")

    development = new_record()
    development.update({
        "area_id": area["id"],
        "name": name,
        "unit_type": unit_type,
        "total_units": total_units,
        "first_occupancy_date": iso3(first_occupancy),
        "buildout_months": buildout_months,
        "student_yield_override": float(yield_override) if yield_override is not None else None,
        "entitlement_status": "PROPOSED",
        "_first_occupancy_dt": first_occupancy,
    })
    db.developments[development["id"]] = development
    return respond(dev_serializer(development), 201)


@bp.get("/planning-areas/<area_id>/housing-developments")
def list_developments(area_id):
    authenticate(READ_ROLES_INTERNAL)
    area = get_area(area_id)
    rows = developments_of_area(area["id"])
    for key in ("unit_type", "entitlement_status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return paginate(rows, dev_serializer)


@bp.get("/housing-developments/<development_id>")
def read_development(development_id):
    authenticate(READ_ROLES_INTERNAL)
    return respond(dev_serializer(get_development(development_id)))


@bp.post("/housing-developments/<development_id>/entitlement-advance")
def entitlement_advance(development_id):
    authenticate(["DistrictPlanner"])
    development = get_development(development_id)
    body = body_json()
    to_status = as_enum(need(body, "to_status"), "to_status", core.ENTITLEMENT_STAGES)

    current = development["entitlement_status"]
    if current in ("COMPLETE", "WITHDRAWN"):
        fail("ERR_ENTITLEMENT_STAGE_INVALID")
    if to_status == "WITHDRAWN":
        pass  # reachable from every non-terminal stage
    elif core.ENTITLEMENT_FORWARD.get(current) != to_status:
        fail("ERR_ENTITLEMENT_STAGE_INVALID")

    area = db.areas[development["area_id"]]
    study = db.studies[area["study_id"]]

    # Link 1 - the development itself.
    development["entitlement_status"] = to_status
    touch(development)

    # Link 2 - every COMPLETE run of the study goes STALE, in run creation order.
    staled_run_ids = []
    for run in runs_of_study(study["id"]):
        if run["status"] == "COMPLETE":
            run["status"] = "STALE"
            run["stale_reason"] = "DEVELOPMENT_PIPELINE_CHANGED"
            touch(run)
            staled_run_ids.append(run["id"])

    # Link 3 - the scenarios that cite those runs, in scenario creation order.
    left_under_review = False
    for scenario in scenarios_of_study(study["id"]):
        if scenario["projection_run_id"] not in staled_run_ids:
            continue
        if scenario["status"] not in ("DRAFT", "UNDER_REVIEW", "REVISION"):
            continue
        scenario["projection_stale"] = True
        if scenario["status"] == "UNDER_REVIEW":
            scenario["status"] = "REVISION"
            scenario["revision_reason"] = "PROJECTION_STALE"
            scenario["revision_round"] = scenario["revision_round"] + 1
            left_under_review = True
        touch(scenario)

    # Link 4 - the study reverts when no live scenario is left to comment on.
    if left_under_review and study["status"] == "ENGAGEMENT":
        remaining = [
            s for s in scenarios_of_study(study["id"])
            if s["status"] in ("UNDER_REVIEW", "BOARD_READY")
        ]
        if not remaining:
            study["status"] = "SCENARIO_DEVELOPMENT"
    recompute_study_rollups(study)
    return respond(dev_serializer(development))
