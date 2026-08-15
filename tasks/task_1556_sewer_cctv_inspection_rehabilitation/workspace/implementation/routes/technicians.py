"""Technician endpoints."""
from flask import Blueprint

import db
from middleware import get_actor, require_roles
from response import success_object
from errors import err_invalid_request, err_not_found
from services.common import (
    body, require_string, parse_datetime_field, sweep_notice_expiry,
)

bp = Blueprint("technicians", __name__)

ALL_ROLES = ["DistrictEngineer", "Coder", "QaReviewer", "CrewLead", "CustomerServiceRep"]
CAPABILITIES = {"CODER", "QA_REVIEWER", "CREW_LEAD"}


def tech_view(t):
    return {
        "id": t["id"],
        "full_name": t["full_name"],
        "nassco_cert_number": t["nassco_cert_number"],
        "nassco_cert_expires_at": t["nassco_cert_expires_at"],
        "capabilities": list(t["capabilities"]),
        "active": t["active"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


@bp.post("/sewer/technicians")
def create_technician():
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    payload = body()
    full_name = require_string(payload, "full_name")
    cert_num = require_string(payload, "nassco_cert_number")
    expires = parse_datetime_field(payload, "nassco_cert_expires_at", required=True)
    caps = payload.get("capabilities")
    if not isinstance(caps, list) or not caps:
        raise err_invalid_request("capabilities must be a non-empty list")
    for c in caps:
        if c not in CAPABILITIES:
            raise err_invalid_request(f"unknown capability: {c}")
    active = payload.get("active", True)
    if not isinstance(active, bool):
        raise err_invalid_request("active must be a boolean")
    # uniqueness of nassco_cert_number
    for t in db.technicians.values():
        if t["nassco_cert_number"] == cert_num:
            raise err_invalid_request("nassco_cert_number must be unique")
    ent = {
        "id": db.new_id(),
        "full_name": full_name,
        "nassco_cert_number": cert_num,
        "nassco_cert_expires_at": db._format_iso(expires),
        "capabilities": list(caps),
        "active": active,
    }
    db.stamp_new(ent)
    db.technicians[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(tech_view(ent), status=201)


@bp.get("/sewer/technicians/<id>")
def get_technician(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    t = db.technicians.get(id)
    if t is None:
        raise err_not_found("technician not found")
    return success_object(tech_view(t))


@bp.patch("/sewer/technicians/<id>")
def update_technician(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    t = db.technicians.get(id)
    if t is None:
        raise err_not_found("technician not found")
    payload = body()
    if "nassco_cert_expires_at" in payload:
        exp = parse_datetime_field(payload, "nassco_cert_expires_at", required=True)
        t["nassco_cert_expires_at"] = db._format_iso(exp)
    if "capabilities" in payload:
        caps = payload["capabilities"]
        if not isinstance(caps, list):
            raise err_invalid_request("capabilities must be a list")
        for c in caps:
            if c not in CAPABILITIES:
                raise err_invalid_request(f"unknown capability: {c}")
        t["capabilities"] = list(caps)
    if "active" in payload:
        if not isinstance(payload["active"], bool):
            raise err_invalid_request("active must be a boolean")
        t["active"] = payload["active"]
    db.touch(t)
    sweep_notice_expiry()
    return success_object(tech_view(t))
