"""Recovery machines and their certification verifications (PRD 3.2)."""
from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from middleware import COMPLIANCE_MANAGER, endpoint, read_endpoint
from services import guards

bp = Blueprint("recovery_equipment", __name__)


def derive_status(last_verification_on, instant):
    """CERTIFIED while the verification is within 365 days of the instant."""
    horizon = util.add_days(last_verification_on,
                            constants.EQUIPMENT_VERIFICATION_WINDOW_DAYS)
    if horizon < instant:
        return "VERIFICATION_OVERDUE"
    return "CERTIFIED"


@bp.post("/recovery-equipment")
@endpoint([COMPLIANCE_MANAGER])
def create_equipment():
    payload = validate.body()
    store_id = validate.req_id(payload, "store_id")
    assigned_technician_id = validate.req_id(payload, "assigned_technician_id")
    equipment_serial = validate.req_str(payload, "equipment_serial")
    certified_to_standard = validate.req_enum(payload, "certified_to_standard",
                                              constants.EQUIPMENT_STANDARDS)
    certified_for_pressure_class = validate.req_enum(
        payload, "certified_for_pressure_class", constants.PRESSURE_CLASSES)
    last_verification_on = validate.req_instant(payload, "last_verification_on")
    db.require("stores", store_id)
    db.require("technicians", assigned_technician_id)
    guards.require_unique("recovery_equipment", "equipment_serial", equipment_serial)
    equipment = db.new_entity()
    equipment.update({
        "store_id": store_id,
        "assigned_technician_id": assigned_technician_id,
        "equipment_serial": equipment_serial,
        "certified_to_standard": certified_to_standard,
        "certified_for_pressure_class": certified_for_pressure_class,
        "last_verification_on": last_verification_on,
        "status": derive_status(last_verification_on, db.now()),
    })
    db.insert("recovery_equipment", equipment)
    return response.created(equipment)


@bp.get("/recovery-equipment")
@read_endpoint
def list_equipment():
    filters = {
        "store_id": request.args.get("store_id"),
        "assigned_technician_id": request.args.get("assigned_technician_id"),
        "status": request.args.get("status"),
        "certified_for_pressure_class": request.args.get("certified_for_pressure_class"),
    }
    return response.listing(db.values("recovery_equipment"), filters)


@bp.get("/recovery-equipment/<equipment_id>")
@read_endpoint
def get_equipment(equipment_id):
    return response.ok(db.require("recovery_equipment", equipment_id))


@bp.post("/recovery-equipment/<equipment_id>/verification")
@endpoint([COMPLIANCE_MANAGER])
def verify_equipment(equipment_id):
    payload = validate.body()
    verified_on = validate.req_instant(payload, "verified_on")
    equipment = db.require("recovery_equipment", equipment_id)
    guards.require_not_after_clock(verified_on)
    snap = db.snapshot(equipment)
    equipment["last_verification_on"] = verified_on
    equipment["status"] = "CERTIFIED"
    db.commit(equipment, snap)
    return response.ok(equipment)
