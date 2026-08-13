"""HangarConditionInspection endpoints."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_roles
from envelope import success_list, success_obj
from errors import ApiError, ERR_INSPECTION_NOT_OPEN, ERR_NOT_FOUND, ERR_REMEDIATION_NOTE_REQUIRED
from routes.hangars import get_hangar_or_404
from routes.leases import get_lease_or_404
from services.core import CONDITION_RATINGS, MAINTENANCE_RESPONSIBILITIES, occupying_lease, touch
from timeutil import iso_z
from validators import body, opt_str, paginate, pagination, req_enum

bp = Blueprint("inspections", __name__)


@bp.post("/hangars/<hid>/inspections")
def create_inspection(hid):
    require_roles("AirportManager", "ComplianceOfficer")
    hangar = get_hangar_or_404(hid)
    data = body()
    condition_rating = req_enum(data, "condition_rating", CONDITION_RATINGS)
    responsibility = req_enum(data, "maintenance_responsibility", MAINTENANCE_RESPONSIBILITIES)
    deficiency_note = opt_str(data, "deficiency_note", "")
    occupying = occupying_lease(hangar["id"])
    inspection = db.new_entity({
        "hangar_id": hangar["id"],
        # Null-equivalent for a vacant hangar is the empty string.
        "lease_id": occupying["id"] if occupying is not None else "",
        "inspected_at": iso_z(db.clock_now()),
        "condition_rating": condition_rating,
        "maintenance_responsibility": responsibility,
        "deficiency_note": deficiency_note,
        "status": "OPEN",
    })
    db.inspections[inspection["id"]] = inspection
    return success_obj(db.public(inspection), 201)


@bp.get("/hangars/<hid>/inspections")
def list_hangar_inspections(hid):
    require_roles(*ALL_ROLES)
    hangar = get_hangar_or_404(hid)
    items = [i for i in db.inspections.values() if i["hangar_id"] == hangar["id"]]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(i) for i in page], limit, offset, total)


@bp.get("/leases/<lid>/inspections")
def list_lease_inspections(lid):
    require_roles(*ALL_ROLES)
    lease = get_lease_or_404(lid)
    items = [i for i in db.inspections.values() if i["lease_id"] == lease["id"]]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(i) for i in page], limit, offset, total)


@bp.post("/inspections/<iid>/close")
def close_inspection(iid):
    require_roles("AirportManager")
    inspection = db.inspections.get(iid)
    if inspection is None:
        raise ApiError(ERR_NOT_FOUND, "Inspection not found", 404)
    if inspection["status"] != "OPEN":
        raise ApiError(ERR_INSPECTION_NOT_OPEN, "Inspection must be OPEN to close", 409)
    data = body()
    remediation_note = opt_str(data, "remediation_note")
    if (
        inspection["maintenance_responsibility"] == "TENANT"
        and inspection["condition_rating"] in ("POOR", "OUT_OF_SERVICE")
        and not (remediation_note and remediation_note.strip())
    ):
        raise ApiError(ERR_REMEDIATION_NOTE_REQUIRED, "Closing a TENANT-responsibility POOR/OUT_OF_SERVICE inspection requires a remediation note", 422)
    inspection["status"] = "CLOSED"
    touch(inspection)
    hangar = db.hangars.get(inspection["hangar_id"])
    if hangar is not None:
        # Latest CLOSED inspection wins; closing bumps the hangar version and
        # the compound posture re-derives from the new rating.
        hangar["condition_rating"] = inspection["condition_rating"]
        touch(hangar)
    return success_obj(db.public(inspection), 200)
