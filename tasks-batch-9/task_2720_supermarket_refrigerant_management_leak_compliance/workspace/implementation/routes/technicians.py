"""Technicians and their suspension loop (PRD 3.2)."""
from flask import Blueprint, request

import constants
import db
import response
import validate
from middleware import COMPLIANCE_MANAGER, endpoint, read_endpoint
from services import guards

bp = Blueprint("technicians", __name__)


@bp.post("/technicians")
@endpoint([COMPLIANCE_MANAGER])
def create_technician():
    payload = validate.body()
    full_name = validate.req_str(payload, "full_name")
    epa_certification_number = validate.req_str(payload, "epa_certification_number")
    certification_type = validate.req_enum(payload, "certification_type",
                                           constants.CERTIFICATION_TYPES)
    certification_expires_on = validate.req_instant(payload, "certification_expires_on")
    guards.require_unique("technicians", "epa_certification_number",
                          epa_certification_number)
    technician = db.new_entity()
    technician.update({
        "full_name": full_name,
        "epa_certification_number": epa_certification_number,
        "certification_type": certification_type,
        "certification_expires_on": certification_expires_on,
        "status": "ACTIVE",
        "suspension_reason_code": None,
        "repair_attempt_count": 0,
    })
    db.insert("technicians", technician)
    return response.created(technician)


@bp.get("/technicians")
@read_endpoint
def list_technicians():
    filters = {
        "certification_type": request.args.get("certification_type"),
        "status": request.args.get("status"),
    }
    return response.listing(db.values("technicians"), filters)


@bp.get("/technicians/<technician_id>")
@read_endpoint
def get_technician(technician_id):
    return response.ok(db.require("technicians", technician_id))


@bp.post("/technicians/<technician_id>/status-change")
@endpoint([COMPLIANCE_MANAGER])
def change_technician_status(technician_id):
    payload = validate.body()
    new_status = validate.req_enum(payload, "new_status",
                                   constants.TECHNICIAN_STATUSES)
    reason_code = validate.req_str(payload, "reason_code")
    technician = db.require("technicians", technician_id)
    current = technician["status"]
    guards.require_state(new_status != current)
    snap = db.snapshot(technician)
    technician["status"] = new_status
    if new_status == "SUSPENDED":
        technician["suspension_reason_code"] = reason_code
    else:
        technician["suspension_reason_code"] = None
    db.commit(technician, snap)
    return response.ok(technician)
