"""Studios, studio assignments, housing units and housing assignments."""

from datetime import timedelta

import calc
import domain as D
import store as K
from auth import authorize
from envelope import object_response, paged, query_flag, query_str
from errors import ApiError
from flask import Blueprint
from store import create_row, store, touch
from validate import (bad, body, d, ds, fk, occ, opt_bool, opt_enum,
                      opt_enum_list, opt_int, opt_str, path_row, req_date,
                      req_enum_list, req_int, req_str)

bp = Blueprint("facilities", __name__)

FACILITY_CODE_PATTERN = r"^[A-Z0-9_-]{2,16}$"
READ_STUDIO_ROLES = ["FacilitiesManager", "ProgramAdmin", "Funder"]
READ_HOUSING_ROLES = ["ProgramAdmin", "FacilitiesManager"]
RESIDENCY_TERMINAL = ("COMPLETED", "TERMINATED", "WITHDRAWN")


# ---------------------------------------------------------------- studios
@bp.route("/studios", methods=["POST"])
def create_studio():
    authorize(["FacilitiesManager", "ProgramAdmin"])
    b = body()
    code = req_str(b, "code", min_len=2, max_len=16, pattern=FACILITY_CODE_PATTERN)
    tags = req_enum_list(b, "capability_tags", K.CAPABILITY_TAGS, allow_empty=False)
    ventilation = opt_enum(b, "ventilation_class", K.VENTILATION_CLASSES, default="NONE")
    headcount = req_int(b, "max_concurrent_residents", minimum=1)
    status = opt_enum(b, "status", K.STUDIO_STATUSES, default="AVAILABLE")

    for row in store.studios.values():
        if row["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", "studio code %s already exists" % code)

    row = create_row(store.studios, {
        "code": code,
        "capability_tags": tags,
        "ventilation_class": ventilation,
        "max_concurrent_residents": headcount,
        "status": status,
        "reserved_resident_days": 0,
        "active_assignment_count": 0,
    })
    return object_response(D.ser_studio(row), 201)


@bp.route("/studios", methods=["GET"])
def list_studios():
    authorize(READ_STUDIO_ROLES)
    status = query_str("status")
    ventilation = query_str("ventilation_class")
    tag = query_str("capability_tag")
    rows = D.by_seq(list(store.studios.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if ventilation is not None:
        rows = [r for r in rows if r["ventilation_class"] == ventilation]
    if tag is not None:
        rows = [r for r in rows if tag in r["capability_tags"]]
    return paged(rows, D.ser_studio)


@bp.route("/studios/<studio_id>", methods=["GET"])
def get_studio(studio_id):
    authorize(READ_STUDIO_ROLES)
    row = path_row(store.studios, studio_id, "ERR_STUDIO_NOT_FOUND")
    return object_response(D.ser_studio(row))


@bp.route("/studios/<studio_id>", methods=["PATCH"])
def patch_studio(studio_id):
    authorize(["FacilitiesManager"])
    row = path_row(store.studios, studio_id, "ERR_STUDIO_NOT_FOUND")
    b = body()
    tags = opt_enum_list(b, "capability_tags", K.CAPABILITY_TAGS, allow_empty=False)
    ventilation = opt_enum(b, "ventilation_class", K.VENTILATION_CLASSES)
    headcount = opt_int(b, "max_concurrent_residents", minimum=1)
    status = opt_enum(b, "status", K.STUDIO_STATUSES)

    if tags is not None:
        row["capability_tags"] = tags
    if ventilation is not None:
        row["ventilation_class"] = ventilation
    if headcount is not None:
        row["max_concurrent_residents"] = headcount
    if status is not None:
        row["status"] = status
    touch(row)
    return object_response(D.ser_studio(row))


# ---------------------------------------------------------------- studio occupancy rules
def _active_studio_rows(studio_id, exclude_id=None):
    out = []
    for sa in D.studio_assignments_of(studio_id):
        if sa["status"] != "ACTIVE" or sa["id"] == exclude_id:
            continue
        out.append(sa)
    return D.by_seq(out)


def _single_occupancy_free(studio, start, end):
    """Buffered closed-interval rule; True when the window is bookable."""
    for sa in _active_studio_rows(studio["id"]):
        if calc.studio_interval_conflict(d(sa["start_date"]), d(sa["end_date"]),
                                         start, end):
            return False
    return True


def _shared_capacity_free(studio, start, end):
    """Aggregate headcount rule, evaluated date by date over the request."""
    limit = int(studio["max_concurrent_residents"])
    rows = [(d(sa["start_date"]), d(sa["end_date"])) for sa in
            _active_studio_rows(studio["id"])]
    day = start
    while day <= end:
        covering = 1
        for existing_start, existing_end in rows:
            if existing_start <= day <= existing_end:
                covering += 1
        if covering > limit:
            return False
        day = day + timedelta(days=1)
    return True


def _studio_has_room(studio, start, end):
    if int(studio["max_concurrent_residents"]) == 1:
        return _single_occupancy_free(studio, start, end)
    return _shared_capacity_free(studio, start, end)


def _discipline_requirements(res):
    """(required capability tags, required ventilation rank) for the residency."""
    discipline = D.residency_discipline(res)
    if discipline is None:
        return set(), 0
    return (set(discipline["required_capability_tags"]),
            calc.ventilation_rank(discipline["required_ventilation_class"]))


def _ventilation_sufficient(studio, required_rank, hazmat):
    rank = calc.ventilation_rank(studio["ventilation_class"])
    if rank < required_rank:
        return False
    if hazmat and rank < calc.ventilation_rank("FUME_HOOD"):
        return False
    return True


@bp.route("/studio-assignments", methods=["POST"])
def create_studio_assignment():
    authorize(["FacilitiesManager", "ProgramAdmin"])
    b = body()
    # group 2 -- body foreign keys in declaration order
    res = fk(b, "residency_id", store.residencies, "ERR_RESIDENCY_NOT_FOUND")
    studio = fk(b, "studio_id", store.studios, "ERR_STUDIO_NOT_FOUND")
    # group 3 -- shape and declared ranges
    req_str(b, "residency_id")
    start = req_date(b, "start_date")
    end = req_date(b, "end_date")
    req_int(b, "expected_residency_version", minimum=0)
    opt_str(b, "studio_id")
    if end < start:
        bad("end_date must not fall earlier than start_date")
    # group 4 -- the optimistic-concurrency guard on the parent residency
    occ(b, "expected_residency_version", res)

    # group 6 -- the residency's lifecycle axis, then its calendar
    if res["status"] in RESIDENCY_TERMINAL:
        raise ApiError("ERR_RESIDENCY_STATE_INVALID",
                       "a residency in %s books no studio" % res["status"])
    if res.get("session_start_date") is None:
        raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                       "an unscheduled residency has no session to book inside")

    # group 6 -- an explicitly named studio must be available
    if studio is not None and studio["status"] != "AVAILABLE":
        raise ApiError("ERR_FACILITY_UNAVAILABLE",
                       "studio %s is %s" % (studio["code"], studio["status"]))
    # group 7 -- safety before geometry
    if res["compliance_status"] == "SUSPENDED":
        raise ApiError("ERR_COMPLIANCE_SUSPENDED",
                       "the resident's safety clearance is suspended")

    required_tags, required_rank = _discipline_requirements(res)
    hazmat = D.residency_hazmat(res)
    if studio is not None:
        if not required_tags.issubset(set(studio["capability_tags"])):
            raise ApiError("ERR_STUDIO_CAPABILITY_MISMATCH",
                           "studio %s lacks a required capability" % studio["code"])
        if not _ventilation_sufficient(studio, required_rank, hazmat):
            raise ApiError("ERR_VENTILATION_INSUFFICIENT",
                           "studio %s does not ventilate this practice" % studio["code"])

    # group 9 -- the window must lie inside the session
    session_start = d(res["session_start_date"])
    session_end = d(res.get("session_end_date"))
    if start < session_start or (session_end is not None and end > session_end):
        raise ApiError("ERR_ASSIGNMENT_OUTSIDE_SESSION",
                       "the studio window falls outside the residency session")

    selection_mode = "EXPLICIT"
    if studio is None:
        selection_mode = "AUTO_SELECTED"
        candidates = []
        for row in store.studios.values():
            if row["status"] != "AVAILABLE":
                continue
            if not required_tags.issubset(set(row["capability_tags"])):
                continue
            if not _ventilation_sufficient(row, required_rank, hazmat):
                continue
            if not _studio_has_room(row, start, end):
                continue
            candidates.append(row)
        if not candidates:
            raise ApiError("ERR_NO_STUDIO_AVAILABLE",
                           "no studio survives the eligibility filter for this window")
        studio = sorted(candidates, key=calc.studio_rank_key)[0]
    else:
        # group 9 -- one of two mutually exclusive occupancy rules
        if int(studio["max_concurrent_residents"]) == 1:
            if not _single_occupancy_free(studio, start, end):
                raise ApiError("ERR_STUDIO_INTERVAL_CONFLICT",
                               "the window collides with an active occupancy plus its "
                               "turnaround buffer")
        elif not _shared_capacity_free(studio, start, end):
            raise ApiError("ERR_STUDIO_CAPACITY_EXCEEDED",
                           "the shared studio's headcount is exceeded on at least one date")

    row = create_row(store.studio_assignments, {
        "studio_id": studio["id"],
        "residency_id": res["id"],
        "start_date": ds(start),
        "end_date": ds(end),
        "occupied_days": calc.studio_occupied_days(start, end),
        "status": "ACTIVE",
        "selection_mode": selection_mode,
        "released_reason": None,
    })
    D.recompute_studio_ledger(studio)
    touch(studio)
    res["assigned_studio_code"] = studio["code"]
    touch(res)
    return object_response(D.ser_studio_assignment(row), 201)


@bp.route("/studio-assignments", methods=["GET"])
def list_studio_assignments():
    authorize(READ_STUDIO_ROLES)
    filters = {
        "studio_id": query_str("studio_id"),
        "residency_id": query_str("residency_id"),
        "status": query_str("status"),
        "selection_mode": query_str("selection_mode"),
    }
    rows = D.by_seq(list(store.studio_assignments.values()))
    for key, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return paged(rows, D.ser_studio_assignment)


@bp.route("/studio-assignments/<assignment_id>", methods=["GET"])
def get_studio_assignment(assignment_id):
    authorize(READ_STUDIO_ROLES)
    row = path_row(store.studio_assignments, assignment_id, "ERR_STUDIO_ASSIGNMENT_NOT_FOUND")
    return object_response(D.ser_studio_assignment(row))


@bp.route("/studio-assignments/<assignment_id>/release", methods=["POST"])
def release_studio_assignment(assignment_id):
    authorize(["FacilitiesManager", "ProgramAdmin"])
    row = path_row(store.studio_assignments, assignment_id, "ERR_STUDIO_ASSIGNMENT_NOT_FOUND")
    b = body()
    reason = opt_str(b, "reason", min_len=1, max_len=1000)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID",
                       "RELEASED is terminal; this assignment is already %s" % row["status"])

    row["status"] = "RELEASED"
    row["released_reason"] = reason
    touch(row)
    studio = store.studios.get(row["studio_id"])
    if studio is not None:
        D.recompute_studio_ledger(studio)
        touch(studio)
    res = store.residencies.get(row["residency_id"])
    if res is not None:
        res["assigned_studio_code"] = None
        touch(res)
    return object_response(D.ser_studio_assignment(row))


# ---------------------------------------------------------------- housing units
@bp.route("/housing-units", methods=["POST"])
def create_housing_unit():
    authorize(["ProgramAdmin"])
    b = body()
    code = req_str(b, "code", min_len=2, max_len=16, pattern=FACILITY_CODE_PATTERN)
    beds = req_int(b, "bed_count", minimum=1)
    meal_plan = opt_bool(b, "meal_plan_included", default=False)
    features = req_enum_list(b, "accessibility_features", K.ACCESSIBILITY_FEATURES,
                             allow_empty=True)
    status = opt_enum(b, "status", K.HOUSING_UNIT_STATUSES, default="AVAILABLE")

    for row in store.housing_units.values():
        if row["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", "housing unit code %s already exists" % code)

    row = create_row(store.housing_units, {
        "code": code,
        "bed_count": beds,
        "meal_plan_included": meal_plan,
        "accessibility_features": features,
        "status": status,
        "occupied_bed_nights": 0,
    })
    return object_response(D.ser_housing_unit(row), 201)


@bp.route("/housing-units", methods=["GET"])
def list_housing_units():
    authorize(READ_HOUSING_ROLES)
    status = query_str("status")
    meal_plan = query_flag("meal_plan_included")
    rows = D.by_seq(list(store.housing_units.values()))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if meal_plan is not None:
        rows = [r for r in rows if bool(r["meal_plan_included"]) == meal_plan]
    return paged(rows, D.ser_housing_unit)


@bp.route("/housing-units/<unit_id>", methods=["GET"])
def get_housing_unit(unit_id):
    authorize(READ_HOUSING_ROLES)
    row = path_row(store.housing_units, unit_id, "ERR_HOUSING_UNIT_NOT_FOUND")
    return object_response(D.ser_housing_unit(row))


@bp.route("/housing-units/<unit_id>", methods=["PATCH"])
def patch_housing_unit(unit_id):
    authorize(["ProgramAdmin"])
    row = path_row(store.housing_units, unit_id, "ERR_HOUSING_UNIT_NOT_FOUND")
    b = body()
    beds = opt_int(b, "bed_count", minimum=1)
    meal_plan = opt_bool(b, "meal_plan_included")
    features = opt_enum_list(b, "accessibility_features", K.ACCESSIBILITY_FEATURES,
                             allow_empty=True)
    status = opt_enum(b, "status", K.HOUSING_UNIT_STATUSES)

    if beds is not None:
        row["bed_count"] = beds
    if meal_plan is not None:
        row["meal_plan_included"] = meal_plan
    if features is not None:
        row["accessibility_features"] = features
    if status is not None:
        row["status"] = status
    touch(row)
    return object_response(D.ser_housing_unit(row))


# ---------------------------------------------------------------- housing occupancy rules
def _active_housing_rows(unit_id):
    rows = [ha for ha in D.rows_of(store.housing_assignments, housing_unit_id=unit_id)
            if ha["status"] == "ACTIVE"]
    return D.by_seq(rows)


def _single_bed_free(unit, check_in, check_out):
    """Half-open overlap; adjacency is deliberately not a conflict."""
    for ha in _active_housing_rows(unit["id"]):
        if calc.housing_overlap(d(ha["check_in_date"]), d(ha["check_out_date"]),
                                check_in, check_out):
            return False
    return True


def _multi_bed_free(unit, check_in, check_out):
    """Aggregate bed-night rule, evaluated night by night over the request."""
    limit = int(unit["bed_count"])
    rows = [(d(ha["check_in_date"]), d(ha["check_out_date"]))
            for ha in _active_housing_rows(unit["id"])]
    night = check_in
    while night < check_out:
        occupied = 1
        for existing_in, existing_out in rows:
            if existing_in <= night < existing_out:
                occupied += 1
        if occupied > limit:
            return False
        night = night + timedelta(days=1)
    return True


@bp.route("/housing-assignments", methods=["POST"])
def create_housing_assignment():
    authorize(["ProgramAdmin"])
    b = body()
    # group 2 -- body foreign keys in declaration order
    unit = fk(b, "housing_unit_id", store.housing_units, "ERR_HOUSING_UNIT_NOT_FOUND")
    res = fk(b, "residency_id", store.residencies, "ERR_RESIDENCY_NOT_FOUND")
    # group 3 -- shape and declared ranges
    req_str(b, "housing_unit_id")
    req_str(b, "residency_id")
    check_in = req_date(b, "check_in_date")
    check_out = req_date(b, "check_out_date")
    req_int(b, "expected_housing_unit_version", minimum=0)
    meal_plan = opt_bool(b, "meal_plan_selected", default=False)
    if not check_out > check_in:
        bad("check_out_date must fall strictly later than check_in_date")
    # group 4 -- the OCC guard is taken on the UNIT, the opposite parent from studios
    occ(b, "expected_housing_unit_version", unit)

    # group 6 -- the residency must still be SCHEDULED, and it must have a session
    if res["status"] != "SCHEDULED":
        raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                       "a residency in %s books no bed" % res["status"])
    if res.get("session_start_date") is None:
        raise ApiError("ERR_RESIDENCY_NOT_SCHEDULED",
                       "an unscheduled residency has no session to book inside")
    if unit["status"] != "AVAILABLE":
        raise ApiError("ERR_FACILITY_UNAVAILABLE",
                       "housing unit %s is %s" % (unit["code"], unit["status"]))

    # group 9 -- the exclusive check-out may fall on the morning after the last night
    session_start = d(res["session_start_date"])
    session_end = d(res.get("session_end_date"))
    latest_out = None if session_end is None else session_end + timedelta(days=1)
    if check_in < session_start or (latest_out is not None and check_out > latest_out):
        raise ApiError("ERR_ASSIGNMENT_OUTSIDE_SESSION",
                       "the housing window falls outside the residency session")

    # group 10 -- the meal plan must exist before it can be selected
    if meal_plan and not unit["meal_plan_included"]:
        raise ApiError("ERR_MEAL_PLAN_NOT_AVAILABLE",
                       "housing unit %s carries no meal plan" % unit["code"])

    # group 9 -- one of two mutually exclusive occupancy rules
    if int(unit["bed_count"]) == 1:
        if not _single_bed_free(unit, check_in, check_out):
            raise ApiError("ERR_HOUSING_INTERVAL_CONFLICT",
                           "the window shares a night with an active booking")
    elif not _multi_bed_free(unit, check_in, check_out):
        raise ApiError("ERR_HOUSING_CAPACITY_EXCEEDED",
                       "the unit's bed count is exceeded on at least one night")

    row = create_row(store.housing_assignments, {
        "housing_unit_id": unit["id"],
        "residency_id": res["id"],
        "check_in_date": ds(check_in),
        "check_out_date": ds(check_out),
        "meal_plan_selected": meal_plan,
        "bed_nights": calc.bed_nights(check_in, check_out),
        "status": "ACTIVE",
        "released_reason": None,
    })
    D.recompute_housing_ledger(unit)
    touch(unit)
    res["assigned_housing_unit_code"] = unit["code"]
    touch(res)
    return object_response(D.ser_housing_assignment(row), 201)


@bp.route("/housing-assignments", methods=["GET"])
def list_housing_assignments():
    authorize(READ_HOUSING_ROLES)
    unit_id = query_str("housing_unit_id")
    residency_id = query_str("residency_id")
    status = query_str("status")
    meal_plan = query_flag("meal_plan_selected")
    rows = D.by_seq(list(store.housing_assignments.values()))
    if unit_id is not None:
        rows = [r for r in rows if r["housing_unit_id"] == unit_id]
    if residency_id is not None:
        rows = [r for r in rows if r["residency_id"] == residency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if meal_plan is not None:
        rows = [r for r in rows if bool(r["meal_plan_selected"]) == meal_plan]
    return paged(rows, D.ser_housing_assignment)


@bp.route("/housing-assignments/<assignment_id>", methods=["GET"])
def get_housing_assignment(assignment_id):
    authorize(READ_HOUSING_ROLES)
    row = path_row(store.housing_assignments, assignment_id,
                   "ERR_HOUSING_ASSIGNMENT_NOT_FOUND")
    return object_response(D.ser_housing_assignment(row))


@bp.route("/housing-assignments/<assignment_id>/release", methods=["POST"])
def release_housing_assignment(assignment_id):
    authorize(["ProgramAdmin"])
    row = path_row(store.housing_assignments, assignment_id,
                   "ERR_HOUSING_ASSIGNMENT_NOT_FOUND")
    b = body()
    reason = opt_str(b, "reason", min_len=1, max_len=1000)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID",
                       "RELEASED is terminal; this booking is already %s" % row["status"])

    row["status"] = "RELEASED"
    row["released_reason"] = reason
    touch(row)
    unit = store.housing_units.get(row["housing_unit_id"])
    if unit is not None:
        D.recompute_housing_ledger(unit)
        touch(unit)
    res = store.residencies.get(row["residency_id"])
    if res is not None:
        res["assigned_housing_unit_code"] = None
        touch(res)
    return object_response(D.ser_housing_assignment(row))
