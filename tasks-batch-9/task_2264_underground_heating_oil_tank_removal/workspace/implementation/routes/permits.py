"""Permit filing and the authority's decision (ISSUED / DENIED / REVOKED)."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
from db import assign, create, db
from errors import ApiError
from middleware import (authenticate, body, filter_arg, opt_id, opt_str, pagination,
                        req_enum, resolve)
from response import entity_response, list_response
from services import project as svc

bp = Blueprint("permits", __name__)

READ_ROLES = ("ProjectCoordinator", "FieldTechnician", "LicensedSiteProfessional",
              "ComplianceOfficer")


@bp.post("/permits")
def create_permit():
    authenticate(("ProjectCoordinator",))
    payload = body()
    project_id = opt_id(payload, "tank_project_id")
    project = resolve("tank_projects", project_id) if project_id else None
    if project is None:
        raise ApiError("ERR_INVALID_REQUEST", "tank_project_id is required.")
    permit_type = req_enum(payload, "permit_type", calc.PERMIT_TYPES)

    permit = create("permits", {
        "tank_project_id": project["id"],
        "permit_type": permit_type,
        "submitted_at": db.now(),
        "issued_at": None,
        "notice_effective_at": None,
        "expires_at": None,
        "denial_reason": None,
        "revocation_reason": None,
        "status": "SUBMITTED",
    })
    return entity_response(permit, 201)


@bp.get("/permits")
def list_permits():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    project_id = filter_arg("tank_project_id")
    permit_type = filter_arg("permit_type")
    status = filter_arg("status")
    rows = list(db.permits.values())
    if project_id is not None:
        rows = [r for r in rows if r["tank_project_id"] == project_id]
    if permit_type is not None:
        rows = [r for r in rows if r["permit_type"] == permit_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, limit, offset)


@bp.get("/permits/<permit_id>")
def read_permit(permit_id):
    authenticate(READ_ROLES)
    return entity_response(resolve("permits", permit_id))


@bp.post("/permits/<permit_id>/decision")
def decide_permit(permit_id):
    user_id, role = authenticate(("ComplianceOfficer",))
    permit = resolve("permits", permit_id)
    payload = body()
    decision = req_enum(payload, "decision", ("ISSUED", "DENIED", "REVOKED"))
    denial_reason = opt_str(payload, "denial_reason")
    revocation_reason = opt_str(payload, "revocation_reason")
    if decision == "DENIED" and denial_reason is None:
        raise ApiError("ERR_INVALID_REQUEST", "denial_reason is required.")
    if decision == "REVOKED" and revocation_reason is None:
        raise ApiError("ERR_INVALID_REQUEST", "revocation_reason is required.")

    project = db.tank_projects.get(permit["tank_project_id"])

    if decision == "ISSUED":
        if permit["status"] != "SUBMITTED":
            raise ApiError("ERR_PERMIT_STATE_INVALID")
        if permit["permit_type"] == "MUNICIPAL_DECOMMISSION":
            allowed = ("DISCLOSED",)
        else:
            allowed = ("DISCLOSED", "PERMITTED")
        if project is None or project["status"] not in allowed:
            raise ApiError("ERR_PROJECT_STATE_INVALID")
        issued_at = db.now()
        assign(permit, "status", "ISSUED")
        assign(permit, "issued_at", issued_at)
        assign(permit, "expires_at",
               issued_at + timedelta(days=calc.PERMIT_VALIDITY_DAYS))
        if permit["permit_type"] == "FIRE_MARSHAL_NOTIFICATION":
            assign(permit, "notice_effective_at",
                   issued_at + timedelta(hours=calc.FIRE_MARSHAL_NOTICE_LEAD_HOURS))
        else:
            assign(permit, "notice_effective_at", issued_at)
            assign(project, "status", "PERMITTED")
            svc.recompute_blockers(project)
    elif decision == "DENIED":
        if permit["status"] != "SUBMITTED":
            raise ApiError("ERR_PERMIT_STATE_INVALID")
        assign(permit, "status", "DENIED")
        assign(permit, "denial_reason", denial_reason)
    else:  # REVOKED — the stop-work order
        if permit["status"] != "ISSUED":
            raise ApiError("ERR_PERMIT_STATE_INVALID")
        assign(permit, "status", "REVOKED")
        assign(permit, "revocation_reason", revocation_reason)
        if project is not None:
            for work_order in svc.children("work_orders", project["id"]):
                if work_order["field_status"] in svc.LIVE_FIELD_STATUSES:
                    svc.abort_work_order(work_order, "PERMIT_REVOKED")
            svc.recompute_blockers(project)
    return entity_response(permit)
