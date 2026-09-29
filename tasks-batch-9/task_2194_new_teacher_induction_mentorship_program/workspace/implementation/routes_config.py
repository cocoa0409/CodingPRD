"""Sites, cohorts, milestones and the logical-clock test hook."""

import re

from flask import Blueprint

import calc
import cascades
import domain
from auth import ADMIN, LEAD, MENTOR, NOVICE, STATE, guard, own_site
from envelope import list_response, object_response, pagination, row_response
from errors import ApiError
from store import db, iso, new_row, now, sorted_rows, touch
from validators import (apply_filters, body, datetime_field, enum_field, fk,
                        int_field, path_row, str_field, bool_field)

bp = Blueprint("config", __name__)

SITE_CODE_RE = re.compile(r"^[A-Z0-9]{3,10}$")
MILESTONE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


# ----------------------------------------------------------------------- sites

@bp.post("/sites")
@guard([ADMIN])
def create_site():
    data = body()
    name = str_field(data, "name", 1, 120)
    site_code = str_field(data, "site_code", 3, 10)
    if not SITE_CODE_RE.match(site_code):
        raise ApiError("ERR_INVALID_REQUEST", "site_code must be uppercase alphanumeric.")
    region_code = enum_field(data, "region_code", calc.REGIONS)
    slot_cap = int_field(data, "mentor_slot_cap", 1, 40, required=False, default=6)
    for site in db.sites.values():
        if site.get("site_code") == site_code:
            raise ApiError("ERR_DUPLICATE_SITE_CODE")
    row = new_row({
        "name": name,
        "site_code": site_code,
        "region_code": region_code,
        "status": "OPEN",
        "mentor_slot_cap": slot_cap,
        "active_match_count": 0,
        "closed_at": None,
    })
    db.sites[row["id"]] = row
    return row_response(row, 201)


@bp.get("/sites")
@guard([ADMIN, STATE])
def list_sites():
    rows = sorted_rows(list(db.sites.values()))
    rows = apply_filters(rows, {"region_code": ("region_code", "str"),
                                "status": ("status", "str")})
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/sites/<row_id>")
@guard([ADMIN, LEAD, STATE])
def get_site(row_id):
    row = path_row("sites", row_id)
    own_site(row["id"])
    return row_response(row)


@bp.post("/sites/<row_id>/close")
@guard([ADMIN])
def close_site(row_id):
    row = path_row("sites", row_id)
    data = body()
    str_field(data, "reason", 1, 1000)
    if row.get("status") != "OPEN":
        raise ApiError("ERR_SITE_CLOSED")
    row["status"] = "CLOSED"
    row["closed_at"] = iso(now())
    touch(row)
    return row_response(row)


# --------------------------------------------------------------------- cohorts

@bp.post("/cohorts")
@guard([ADMIN])
def create_cohort():
    data = body()
    name = str_field(data, "name", 1, 120)
    program_year = int_field(data, "program_year", 2020, 2100)
    region_code = enum_field(data, "region_code", calc.REGIONS)
    required = int_field(data, "seminar_sessions_required", 1, 24, required=False, default=6)
    row = new_row({
        "name": name,
        "program_year": program_year,
        "region_code": region_code,
        "seminar_sessions_required": required,
        "status": "FORMING",
        "enrolled_novice_count": 0,
        "closed_at": None,
    })
    db.cohorts[row["id"]] = row
    return row_response(row, 201)


@bp.get("/cohorts")
@guard([ADMIN, LEAD, STATE])
def list_cohorts():
    rows = sorted_rows(list(db.cohorts.values()))
    rows = apply_filters(rows, {"program_year": ("program_year", "int"),
                                "region_code": ("region_code", "str"),
                                "status": ("status", "str")})
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/cohorts/<row_id>")
@guard([ADMIN, LEAD, STATE])
def get_cohort(row_id):
    return row_response(path_row("cohorts", row_id))


@bp.post("/cohorts/<row_id>/close")
@guard([ADMIN])
def close_cohort(row_id):
    row = path_row("cohorts", row_id)
    data = body()
    target = enum_field(data, "target_status", ("RUNNING", "CLOSED"))
    if target != "CLOSED":
        # The step from FORMING to RUNNING is never requested explicitly.
        raise ApiError("ERR_COHORT_STATE_INVALID")
    if row.get("status") not in ("FORMING", "RUNNING"):
        raise ApiError("ERR_COHORT_STATE_INVALID")
    for session in domain.sessions_of_cohort(row["id"]):
        if session.get("status") == "SCHEDULED":
            raise ApiError("ERR_COHORT_STATE_INVALID")
    row["status"] = "CLOSED"
    row["closed_at"] = iso(now())
    touch(row)
    return row_response(row)


# ------------------------------------------------------------------ milestones

@bp.post("/milestones")
@guard([ADMIN])
def create_milestone():
    data = body()
    prerequisite = fk("milestones", data, "prerequisite_milestone_id")
    if data.get("prerequisite_milestone_id") is not None and prerequisite is None:
        raise ApiError("ERR_INVALID_REQUEST", "prerequisite_milestone_id must be a string.")
    code = str_field(data, "code", 3, 40)
    if not MILESTONE_CODE_RE.match(code):
        raise ApiError("ERR_INVALID_REQUEST", "code must be uppercase snake case.")
    title = str_field(data, "title", 1, 160)
    sequence_index = int_field(data, "sequence_index", 1, 20)
    contact_minutes = int_field(data, "required_contact_minutes", 0, 100000)
    cycles = int_field(data, "required_observation_cycles", 0, 12)
    seminars = int_field(data, "required_credited_seminars", 0, 24)
    stage = enum_field(data, "license_stage_unlocked", calc.LICENSE_STAGES)
    gates = bool_field(data, "gates_license_recommendation", required=False, default=False)
    if prerequisite is not None:
        if int(prerequisite.get("sequence_index") or 0) >= sequence_index:
            raise ApiError("ERR_MILESTONE_CYCLE")
    for milestone in db.milestones.values():
        if milestone.get("code") == code or milestone.get("sequence_index") == sequence_index:
            raise ApiError("ERR_DUPLICATE_MILESTONE_CODE")
    row = new_row({
        "code": code,
        "title": title,
        "sequence_index": sequence_index,
        "required_contact_minutes": contact_minutes,
        "required_observation_cycles": cycles,
        "required_credited_seminars": seminars,
        "license_stage_unlocked": stage,
        "gates_license_recommendation": gates,
        "prerequisite_milestone_id": prerequisite["id"] if prerequisite else None,
    }, versioned=False)
    db.milestones[row["id"]] = row
    return row_response(row, 201)


@bp.get("/milestones")
@guard([ADMIN, LEAD, MENTOR, NOVICE, STATE])
def list_milestones():
    rows = domain.milestones_sorted()
    rows = apply_filters(rows, {
        "prerequisite_milestone_id": ("prerequisite_milestone_id", "str"),
        "gates_license_recommendation": ("gates_license_recommendation", "bool"),
    })
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/milestones/<row_id>")
@guard([ADMIN, LEAD, MENTOR, NOVICE, STATE])
def get_milestone(row_id):
    return row_response(path_row("milestones", row_id))


# ------------------------------------------------------------------ clock hook

@bp.post("/_clock/set_current_utc")
def set_clock():
    data = body()
    moment = datetime_field(data, "current_utc")
    db.clock = moment
    cascades.lapse_sweep()
    return object_response({"current_utc": iso(moment)})
