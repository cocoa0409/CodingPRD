"""PestInspection endpoints: record (QATechnician) / verify (QAManager, SoD)."""
from flask import Blueprint

import db
from db import new_common, new_id, store, touch
from errors import ApiError
from middleware import ALL_ROLES, get_context, require_roles
from response import created, ok, paginate
from services.cascades import pest_critical_cascade, zone_view
from validation import fk_exists, raw_body, require_path_entity, validate_schema

bp = Blueprint("inspections", __name__)

SEVERITIES = ["NONE", "MINOR", "CRITICAL"]


@bp.post("/pest-inspections")
def create_inspection():
    uid, role, _ = get_context()
    require_roles(["QATechnician"])
    body = raw_body()
    zone = fk_exists(store.warehouse_zones, body, "zone_id", "ERR_ZONE_NOT_FOUND")
    validate_schema(body, {
        "zone_id": ("string", True, None),
        "severity": ("enum", True, SEVERITIES),
        "notes": ("string", False, None),
    })
    inspection = {
        "id": new_id(),
        "zone_id": zone["id"],
        "severity": body["severity"],
        "notes": body.get("notes"),
        "recorded_by_user_id": uid,
        "status": "RECORDED",
        "verified_by_user_id": None,
        "verified_at": None,
    }
    new_common(inspection)
    store.pest_inspections[inspection["id"]] = inspection
    return created(inspection)


@bp.get("/pest-inspections")
def list_inspections():
    get_context()
    require_roles(ALL_ROLES)
    rows = list(store.pest_inspections.values())
    rows = paginate.filter(rows, "zone_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/pest-inspections/<inspection_id>")
def get_inspection(inspection_id):
    get_context()
    require_roles(ALL_ROLES)
    return ok(require_path_entity(store.pest_inspections, inspection_id,
                                  "ERR_INSPECTION_NOT_FOUND"))


@bp.post("/pest-inspections/<inspection_id>/verify")
def verify_inspection(inspection_id):
    uid, role, _ = get_context()
    require_roles(["QAManager"])
    inspection = require_path_entity(store.pest_inspections, inspection_id,
                                     "ERR_INSPECTION_NOT_FOUND")
    if uid == inspection["recorded_by_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Verifier must differ from the recording user")
    if inspection["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection is already VERIFIED")
    inspection["status"] = "VERIFIED"
    inspection["verified_by_user_id"] = uid
    inspection["verified_at"] = db.clock_now()
    touch(inspection)
    zone = store.warehouse_zones[inspection["zone_id"]]
    if inspection["severity"] == "MINOR":
        if zone["pest_posture"] == "CLEAR":
            zone["pest_posture"] = "MONITORING"
            touch(zone)
    elif inspection["severity"] == "NONE":
        if zone["pest_posture"] == "MONITORING":
            zone["pest_posture"] = "CLEAR"
            touch(zone)
    else:  # CRITICAL
        if zone["pest_posture"] in ("CLEAR", "MONITORING"):
            zone["pest_posture"] = "QUARANTINED"
            zone["quarantined_at"] = db.clock_now()
            touch(zone)
            pest_critical_cascade(zone)
    return ok(inspection)
