"""Permits (PRD 3.3)."""

from flask import Blueprint, request

from db import store
from errors import (ERR_INVALID_WINDOW, ERR_JOB_STOPPED,
                    ERR_PERMIT_JHA_MISMATCH, ERR_PERMIT_SPACE_OCCUPIED,
                    ERR_PERMIT_WINDOW_INVALID, conflict, invalid_state,
                    not_found, unprocessable)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.calculations import approved_jha
from util import (get_body, list_paginated, new_entity, now, req_field, touch)

bp = Blueprint("permits", __name__)

PERMIT_TYPES = ["CONFINED_SPACE", "HOT_WORK", "LINE_BREAK"]
PERMIT_STATUSES = ["ISSUED", "ACTIVE", "SUSPENDED", "CLOSED", "REVOKED", "EXPIRED"]


def _get_permit(permit_id):
    permit = store.permits.get(permit_id)
    if permit is None:
        raise not_found("Permit not found")
    return permit


@bp.post("/v1/permits")
def create_permit():
    require_roles(["FieldSupervisor"])
    body = get_body()
    job_id = req_field(body, "job_id")
    permit_type = req_field(body, "permit_type", choices=PERMIT_TYPES)
    space_id = req_field(body, "space_id")
    valid_from = req_field(body, "valid_from", kind="datetime")
    valid_until = req_field(body, "valid_until", kind="datetime")
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("Job not found")
    if job["execution_status"] not in ("SCHEDULED", "MOBILIZED", "IN_PROGRESS"):
        raise invalid_state(
            "Permits can only be raised while the job is SCHEDULED, MOBILIZED or IN_PROGRESS")
    if not valid_until > valid_from:
        raise unprocessable(ERR_INVALID_WINDOW,
                            "valid_until must be later than valid_from")
    permit = new_entity(store.permits, {
        "job_id": job_id,
        "permit_type": permit_type,
        "space_id": space_id,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "status": "ISSUED",
    })
    return success_object(permit, status=201)


@bp.get("/v1/permits")
def list_permits():
    require_roles(ALL_ROLES)
    filters = {}
    for param in ("job_id", "status"):
        if request.args.get(param) is not None:
            filters[param] = request.args[param]
    page, limit, offset, total = list_paginated(store.permits, filters, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/permits/<permitId>")
def get_permit(permitId):
    require_roles(ALL_ROLES)
    return success_object(_get_permit(permitId))


@bp.post("/v1/permits/<permitId>/activate")
def activate_permit(permitId):
    require_roles(["FieldSupervisor"])
    permit = _get_permit(permitId)
    if permit["status"] not in ("ISSUED", "SUSPENDED"):
        raise invalid_state("Only an ISSUED or SUSPENDED permit can be activated")
    job = store.jobs[permit["job_id"]]
    if job["safety_status"] != "CLEAR":
        raise conflict(ERR_JOB_STOPPED, "Job safety status is STOP_WORK")
    if permit["permit_type"] == "CONFINED_SPACE":
        jha = approved_jha(permit["job_id"])
        if jha is None or not jha["confined_space"]:
            raise unprocessable(
                ERR_PERMIT_JHA_MISMATCH,
                "The job's latest APPROVED JHA does not declare confined space")
    for other in job_permits_for(permit["job_id"]):
        if (other["id"] != permit["id"] and other["space_id"] == permit["space_id"]
                and other["status"] == "ACTIVE"):
            raise conflict(ERR_PERMIT_SPACE_OCCUPIED,
                           "Another permit is already ACTIVE for this space")
    current = now()
    if not (permit["valid_from"] <= current <= permit["valid_until"]):
        raise unprocessable(ERR_PERMIT_WINDOW_INVALID,
                            "The logical clock is outside the permit's validity window")
    permit["status"] = "ACTIVE"
    touch(permit)
    return success_object(permit)


def job_permits_for(job_id):
    return [p for p in store.permits.values() if p["job_id"] == job_id]


@bp.post("/v1/permits/<permitId>/suspend")
def suspend_permit(permitId):
    require_roles(["SafetyManager"])
    permit = _get_permit(permitId)
    if permit["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE permit can be suspended")
    permit["status"] = "SUSPENDED"
    touch(permit)
    return success_object(permit)


@bp.post("/v1/permits/<permitId>/close")
def close_permit(permitId):
    require_roles(["FieldSupervisor"])
    permit = _get_permit(permitId)
    if permit["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE permit can be closed")
    permit["status"] = "CLOSED"
    touch(permit)
    return success_object(permit)


@bp.post("/v1/permits/<permitId>/revoke")
def revoke_permit(permitId):
    require_roles(["SafetyManager"])
    permit = _get_permit(permitId)
    if permit["status"] not in ("ISSUED", "ACTIVE", "SUSPENDED"):
        raise invalid_state("Only an ISSUED, ACTIVE or SUSPENDED permit can be revoked")
    permit["status"] = "REVOKED"
    touch(permit)
    return success_object(permit)
