"""Worksites and work areas (PRD 3.1)."""

import re

from flask import Blueprint

import constants as C
import sync
from db import new_row, store
from middleware import authenticate
from routes.common import filtered, lookup, paged, single
from validation import (bool_field, body, enum_field, id_field, int_field,
                        qs_bool, qs_enum, qs_str, str_field)

bp = Blueprint("worksites", __name__)

READ_WORKSITE_ROLES = ("ProgramAdmin", "SafetyOfficer", "SiteManager", "ThreatTeamLead", "ComplianceAuditor")
LIST_WORKSITE_ROLES = ("ProgramAdmin", "SafetyOfficer", "SiteManager", "ComplianceAuditor")
READ_AREA_ROLES = ("ProgramAdmin", "SafetyOfficer", "SiteManager", "SecurityCoordinator", "ThreatTeamLead", "ComplianceAuditor")

_STATE_CODE = re.compile(r"^[A-Z]{2}$")


@bp.post("/worksites")
def create_worksite():
    authenticate(("ProgramAdmin",))
    data = body()
    name = str_field(data, "name", True, 1, 120)
    state_code = str_field(data, "state_code", True, 2, 2)
    if not _STATE_CODE.match(state_code):
        from validation import bad
        bad("Field 'state_code' must be exactly two uppercase letters.")
    employee_count = int_field(data, "employee_count", True, 1)

    row = new_row({
        "name": name,
        "state_code": state_code,
        "employee_count": employee_count,
        "violent_incident_count_12mo": 0,
        "high_risk_flag": False,
    })
    store.worksites[row["id"]] = row
    return single(row, 201)


@bp.get("/worksites/<worksite_id>")
def get_worksite(worksite_id):
    authenticate(READ_WORKSITE_ROLES)
    return single(lookup(store.worksites, worksite_id, "ERR_WORKSITE_NOT_FOUND"))


@bp.get("/worksites")
def list_worksites():
    authenticate(LIST_WORKSITE_ROLES)
    filters = {
        "state_code": qs_str("state_code"),
        "high_risk_flag": qs_bool("high_risk_flag"),
    }
    return paged(filtered(list(store.worksites.values()), filters))


@bp.post("/work-areas")
def create_work_area():
    authenticate(("ProgramAdmin",))
    data = body()
    worksite_id = id_field(data, "worksite_id", True)
    name = str_field(data, "name", True, 1, 120)
    job_function = enum_field(data, "job_function", C.JOB_FUNCTIONS, True)
    public_access = bool_field(data, "public_access_flag", False, False)
    lone_worker = bool_field(data, "lone_worker_flag", False, False)
    night_shift = bool_field(data, "night_shift_flag", False, False)
    occupancy_cap = int_field(data, "occupancy_cap", True, 1)

    lookup(store.worksites, worksite_id, "ERR_WORKSITE_NOT_FOUND")

    row = new_row({
        "worksite_id": worksite_id,
        "name": name,
        "job_function": job_function,
        "public_access_flag": public_access,
        "lone_worker_flag": lone_worker,
        "night_shift_flag": night_shift,
        "occupancy_cap": occupancy_cap,
        "restricted_employee_count": 0,
        "current_hazard_score": None,
    })
    store.work_areas[row["id"]] = row

    # Adding an area enlarges the hazard-coverage denominator.
    sync.sync_plans_of_worksite(worksite_id)
    return single(row, 201)


@bp.get("/work-areas/<work_area_id>")
def get_work_area(work_area_id):
    authenticate(READ_AREA_ROLES)
    return single(lookup(store.work_areas, work_area_id, "ERR_WORK_AREA_NOT_FOUND"))


@bp.get("/work-areas")
def list_work_areas():
    authenticate(READ_AREA_ROLES)
    filters = {
        "worksite_id": qs_str("worksite_id"),
        "job_function": qs_enum("job_function", C.JOB_FUNCTIONS),
        "lone_worker_flag": qs_bool("lone_worker_flag"),
    }
    return paged(filtered(list(store.work_areas.values()), filters))
