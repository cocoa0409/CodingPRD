"""Job hazard analyses (PRD 3.3)."""

from flask import Blueprint, request

from db import store
from errors import (ApiError, ERR_JHA_PRESSURE_PLAN_REQUIRED,
                    ERR_SEGREGATION_OF_DUTIES, ERR_STALE_VERSION, bad_request,
                    invalid_state, not_found, unprocessable)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (get_body, is_int, list_paginated, new_entity, opt_field,
                  req_field, touch)

bp = Blueprint("jhas", __name__)

HAZARDS = ["CONFINED_SPACE", "HIGH_PRESSURE_WATER", "CHEMICAL_EXPOSURE",
           "SLIP_TRIP", "ERGONOMIC", "OTHER"]
WATER_SOURCES = ["SITE_POTABLE", "SITE_NONPOTABLE", "TRUCKED_IN"]
JHA_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]


def _get_jha(jha_id):
    jha = store.jhas.get(jha_id)
    if jha is None:
        raise not_found("JobHazardAnalysis not found")
    return jha


@bp.post("/v1/jhas")
def create_jha():
    require_roles(["FieldSupervisor"])
    body = get_body()
    job_id = req_field(body, "job_id")
    confined_space = req_field(body, "confined_space", kind="bool")
    hazards = req_field(body, "hazards", kind="array", choices=HAZARDS)
    max_psi = opt_field(body, "max_operating_pressure_psi", kind="int", gte_zero=True)
    flow = opt_field(body, "planned_water_flow_gpm", kind="number", gte_zero=True)
    water_source = opt_field(body, "water_source", choices=WATER_SOURCES)
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("Job not found")
    if job["execution_status"] in ("CANCELLED", "CLOSED"):
        raise invalid_state("Cannot author a JHA against a terminal job")
    existing = [j for j in store.jhas.values() if j["job_id"] == job_id]
    revision = max((j["revision_number"] for j in existing), default=0) + 1
    jha = new_entity(store.jhas, {
        "job_id": job_id,
        "revision_number": revision,
        "hazards": list(hazards),
        "confined_space": confined_space,
        "max_operating_pressure_psi": max_psi,
        "planned_water_flow_gpm": flow,
        "water_source": water_source,
        "submitted_by": None,
        "approved_by": None,
        "status": "DRAFT",
    })
    return success_object(jha, status=201)


@bp.get("/v1/jhas")
def list_jhas():
    require_roles(ALL_ROLES)
    filters = {}
    for param in ("job_id", "status"):
        if request.args.get(param) is not None:
            filters[param] = request.args[param]
    page, limit, offset, total = list_paginated(store.jhas, filters, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/jhas/<jhaId>")
def get_jha(jhaId):
    require_roles(ALL_ROLES)
    return success_object(_get_jha(jhaId))


@bp.post("/v1/jhas/<jhaId>/submit")
def submit_jha(jhaId):
    user_id, _ = require_roles(["FieldSupervisor"])
    jha = _get_jha(jhaId)
    if jha["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT hazard analysis can be submitted")
    job = store.jobs[jha["job_id"]]
    if job["job_type"] in ("HYDROBLAST", "COMBINED"):
        if (jha["max_operating_pressure_psi"] is None
                or jha["planned_water_flow_gpm"] is None
                or jha["water_source"] is None):
            raise unprocessable(
                ERR_JHA_PRESSURE_PLAN_REQUIRED,
                "HYDROBLAST/COMBINED jobs require the pressure/water plan at submit")
    jha["submitted_by"] = user_id
    jha["status"] = "SUBMITTED"
    touch(jha)
    return success_object(jha)


@bp.post("/v1/jhas/<jhaId>/approve")
def approve_jha(jhaId):
    user_id, _ = require_roles(["SafetyManager"])
    body = get_body()
    if "expected_job_version" not in body or body["expected_job_version"] is None:
        raise bad_request("Missing required field: expected_job_version")
    expected = body["expected_job_version"]
    if not is_int(expected):
        raise bad_request("Field expected_job_version must be an integer")
    jha = _get_jha(jhaId)
    job = store.jobs[jha["job_id"]]
    # OCC on the owning job's version, evaluated before any business gate.
    if expected != job["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_job_version does not match the job's current version")
    if jha["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED hazard analysis can be approved")
    if user_id == jha["submitted_by"]:
        raise unprocessable(ERR_SEGREGATION_OF_DUTIES,
                            "The approver must differ from the submitter")
    jha["approved_by"] = user_id
    jha["status"] = "APPROVED"
    touch(jha)
    for other in store.jhas.values():
        if (other["job_id"] == jha["job_id"] and other["id"] != jha["id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(job)  # approval increments the job's version by one
    return success_object(jha)


@bp.post("/v1/jhas/<jhaId>/reject")
def reject_jha(jhaId):
    user_id, _ = require_roles(["SafetyManager"])
    jha = _get_jha(jhaId)
    if jha["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED hazard analysis can be rejected")
    if user_id == jha["submitted_by"]:
        raise unprocessable(ERR_SEGREGATION_OF_DUTIES,
                            "The rejector must differ from the submitter")
    jha["status"] = "REJECTED"
    touch(jha)
    return success_object(jha)


@bp.post("/v1/jhas/<jhaId>/revise")
def revise_jha(jhaId):
    require_roles(["FieldSupervisor"])
    jha = _get_jha(jhaId)
    if jha["status"] != "REJECTED":
        raise invalid_state("Only a REJECTED hazard analysis can be revised")
    jha["status"] = "DRAFT"
    touch(jha)
    return success_object(jha)
