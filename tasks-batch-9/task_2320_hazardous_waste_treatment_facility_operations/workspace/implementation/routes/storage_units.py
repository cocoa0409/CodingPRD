"""Permitted storage units."""

from flask import Blueprint

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import by_created_at, load, reference, respond_list
from services import calc, cascade, derive
from services.tracking import touch
from util import new_id

bp = Blueprint("storage_units", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "ReceivingClerk", "TreatmentOperator", "RegulatoryInspector"]

CREATE_SPEC = {
    "facility_id": {"type": "string", "required": True},
    "unit_code": {"type": "string", "required": True, "non_empty": True},
    "unit_type": {"type": "string", "required": True, "enum": calc.UNIT_TYPES},
    "permitted_capacity_kg": {"type": "number", "required": True, "gt": 0},
    "aisle_width_cm": {"type": "number", "required": True},
    "aisle_free_container_capacity": {"type": "int", "required": True, "ge": 0},
    "inspection_frequency_days": {"type": "int", "required": True, "ge": 1},
    "allowed_compatibility_classes": {"type": "array", "required": True, "non_empty": True,
                                      "items": {"type": "string", "enum": calc.COMPATIBILITY_CLASSES}},
    "air_emission_control_level": {"type": "string", "required": True, "enum": calc.AIR_LEVELS},
    "containment_volume_l": {"type": "number", "required": True, "gt": 0},
}


@bp.post("/tsdf/storage-units")
@endpoint(roles=["PlatformAdmin", "ComplianceManager"], mutating=True)
def create_unit():
    body = schema.body(CREATE_SPEC)
    f = reference("facilities", body["facility_id"])

    for existing in derive.units_of_facility(f["id"]):
        if existing["unit_code"] == body["unit_code"]:
            fail("ERR_DUPLICATE_MANIFEST_NUMBER", "unit_code is already used at this facility")

    ceiling = calc.INSPECTION_FREQUENCY_CEILING[body["unit_type"]]
    if body["inspection_frequency_days"] > ceiling:
        fail("ERR_INSPECTION_FREQUENCY_INVALID")

    stamp = now()
    row = {
        "id": new_id(),
        "facility_id": f["id"],
        "unit_code": body["unit_code"],
        "unit_type": body["unit_type"],
        "permitted_capacity_kg": body["permitted_capacity_kg"],
        "aisle_width_cm": body["aisle_width_cm"],
        "aisle_free_container_capacity": body["aisle_free_container_capacity"],
        "inspection_frequency_days": body["inspection_frequency_days"],
        "allowed_compatibility_classes": body["allowed_compatibility_classes"],
        "air_emission_control_level": body["air_emission_control_level"],
        "containment_volume_l": body["containment_volume_l"],
        "status": "ACTIVE",
        "closure_plan_ref": None,
        "last_inspection_at": stamp,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    insert("units", row)
    return created(derive.project_unit(row))


@bp.get("/tsdf/storage-units/<uid>")
@endpoint(roles=READERS)
def get_unit(uid):
    return ok(derive.project_unit(load("units", uid)))


@bp.get("/tsdf/storage-units")
@endpoint(roles=READERS)
def list_units():
    filters, limit, offset = schema.listing(
        filters=["facility_id", "unit_type", "status", "posture"],
        enums={"unit_type": calc.UNIT_TYPES, "status": calc.UNIT_STATUSES, "posture": calc.POSTURES})
    rows = by_created_at(list(db.units.values()))
    for key in ("facility_id", "unit_type", "status"):
        if key in filters:
            rows = [u for u in rows if u[key] == filters[key]]
    if "posture" in filters:
        rows = [u for u in rows if derive.unit_posture(u) == filters["posture"]]
    return respond_list(rows, derive.project_unit, limit, offset)


@bp.post("/tsdf/storage-units/<uid>/status")
@endpoint(roles=["ComplianceManager"], mutating=True)
def set_unit_status(uid):
    body = schema.body({
        "to_status": {"type": "string", "required": True, "enum": calc.UNIT_STATUSES},
        "closure_plan_ref": {"type": "string"},
    })
    target = body["to_status"]
    if target == "CLOSING" and not body["closure_plan_ref"]:
        fail("ERR_INVALID_REQUEST", "closure_plan_ref is required to begin closure")

    u = load("units", uid)
    current = u["status"]

    if (current, target) == ("ACTIVE", "CLOSING"):
        u["status"] = "CLOSING"
        u["closure_plan_ref"] = body["closure_plan_ref"]
    elif (current, target) == ("CLOSING", "CLOSED"):
        if derive.unit_container_count(u) != 0:
            fail("ERR_INVALID_STATE", "The unit still holds containers")
        for b in derive.batches_of_unit(uid):
            if b["status"] in calc.NON_TERMINAL_BATCH_STATUSES:
                fail("ERR_INVALID_STATE", "The unit still has open treatment batches")
        for order in derive.repair_orders_of_unit(uid):
            if order["status"] != "REPAIRED":
                fail("ERR_INVALID_STATE", "The unit still has unrepaired leaks")
        u["status"] = "CLOSED"
    elif (current, target) == ("CLOSING", "ACTIVE"):
        u["status"] = "ACTIVE"
        u["closure_plan_ref"] = None
    else:
        fail("ERR_INVALID_STATE", "Unsupported storage unit status transition")

    cascade.reconcile_unit(u)
    touch("units", u)
    return ok(derive.project_unit(u))


@bp.get("/tsdf/storage-units/<uid>/containers")
@endpoint(roles=READERS)
def list_unit_containers(uid):
    filters, limit, offset = schema.listing(
        filters=["custody_state", "compliance_state"],
        enums={"custody_state": calc.CUSTODY_STATES, "compliance_state": calc.COMPLIANCE_STATES})
    load("units", uid)
    rows = by_created_at(derive.containers_of_unit(uid))
    for key in ("custody_state", "compliance_state"):
        if key in filters:
            rows = [c for c in rows if c[key] == filters[key]]
    return respond_list(rows, derive.project_container, limit, offset)
