"""Technician and TechnicianCertification endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import err_duplicate_key, err_state_transition, err_validation
from services.common import (
    body, require_string, require_enum, parse_datetime_field, parse_pagination,
    paginate, get_technician, get_certification,
)
from services.calculations import compute_certification_status

bp = Blueprint("technicians", __name__)

CERT_TYPES = {"NETA_LEVEL_2", "NETA_LEVEL_3", "NETA_LEVEL_4", "SWITCHING_QUALIFIED"}


def technician_view(t):
    return {
        "id": t["id"],
        "full_name": t["full_name"],
        "employee_code": t["employee_code"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def certification_view(c):
    # Compute derived status
    status = compute_certification_status(c)
    return {
        "id": c["id"],
        "technician_id": c["technician_id"],
        "cert_type": c["cert_type"],
        "issued_at": c["issued_at"],
        "expires_at": c["expires_at"],
        "revoked_at": c.get("revoked_at"),
        "status": status,
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/technicians")
def create_technician():
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    payload = body()
    full_name = require_string(payload, "full_name")
    employee_code = require_string(payload, "employee_code")
    # Uniqueness: employee_code
    for t in db.technicians.values():
        if t["employee_code"] == employee_code:
            raise err_duplicate_key("employee_code already exists")
    ent = {
        "id": db.new_id(),
        "full_name": full_name,
        "employee_code": employee_code,
        "status": "ACTIVE",
    }
    db.stamp_new(ent)
    db.technicians[ent["id"]] = ent
    return success_object(technician_view(ent), status=201)


@bp.get("/technicians")
def list_technicians():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.technicians.values())
    status = request.args.get("status")
    if status:
        items = [t for t in items if t["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([technician_view(t) for t in page], limit, offset, total)


@bp.get("/technicians/<id>")
def get_technician_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    t = get_technician(id)
    return success_object(technician_view(t))


@bp.post("/technicians/<id>/deactivate")
def deactivate_technician(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    t = get_technician(id)
    if t["status"] != "ACTIVE":
        raise err_state_transition("Technician is not ACTIVE")
    t["status"] = "INACTIVE"
    db.touch(t)
    return success_object(technician_view(t))


@bp.post("/technicians/<id>/certifications")
def create_certification(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    tech = get_technician(id)
    payload = body()
    cert_type = require_enum(payload, "cert_type", CERT_TYPES)
    issued_at_raw = parse_datetime_field(payload, "issued_at", required=True)
    expires_at_raw = parse_datetime_field(payload, "expires_at", required=True)

    if expires_at_raw <= issued_at_raw:
        raise err_validation("expires_at must be strictly after issued_at")

    ent = {
        "id": db.new_id(),
        "technician_id": id,
        "cert_type": cert_type,
        "issued_at": db._format_iso(issued_at_raw),
        "expires_at": db._format_iso(expires_at_raw),
        "revoked_at": None,
    }
    db.stamp_new(ent)
    # Compute initial status
    ent["status"] = compute_certification_status(ent)
    db.technician_certifications[ent["id"]] = ent
    return success_object(certification_view(ent), status=201)


@bp.get("/technicians/<id>/certifications")
def list_certifications(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    tech = get_technician(id)
    limit, offset = parse_pagination()
    items = [c for c in db.technician_certifications.values() if c["technician_id"] == id]
    cert_type = request.args.get("cert_type")
    if cert_type:
        items = [c for c in items if c["cert_type"] == cert_type]
    status = request.args.get("status")
    if status:
        # Need to compute derived status for filtering
        filtered = []
        for c in items:
            if compute_certification_status(c) == status:
                filtered.append(c)
        items = filtered
    page, total = paginate(items, limit, offset)
    return success_list([certification_view(c) for c in page], limit, offset, total)


@bp.post("/certifications/<id>/revoke")
def revoke_certification(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    cert = get_certification(id)
    if cert.get("revoked_at") is not None:
        raise err_state_transition("Certification is already revoked")
    cert["revoked_at"] = db.now_iso()
    cert["status"] = "REVOKED"
    db.touch(cert)
    return success_object(certification_view(cert))
