"""Inspection events: the record, its container cascades and the leak order it spawns."""

from flask import Blueprint, g

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import by_created_at, load, reference, respond_list
from services import calc, cascade, derive
from services.tracking import touch
from util import D, add_days, new_id

bp = Blueprint("inspections", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "TreatmentOperator", "RegulatoryInspector"]

LEAK_FINDING_CODES = ("CONTAINER_LEAK", "TANK_SHELL_CORROSION")
DEFICIENCY_FINDING_CODES = ("LABEL_DEFICIENT", "OVERFILL")

CREATE_SPEC = {
    "storage_unit_id": {"type": "string", "required": True},
    "container_id": {"type": "string"},
    "inspection_type": {"type": "string", "required": True, "enum": calc.INSPECTION_TYPES},
    "finding_code": {"type": "string", "required": True, "enum": calc.FINDING_CODES},
    "measured_organic_vapor_ppm": {"type": "number", "ge": 0},
    "measured_aisle_width_cm": {"type": "number"},
}


@bp.post("/tsdf/inspection-events")
@endpoint(roles=["ComplianceManager", "RegulatoryInspector"], mutating=True)
def create_inspection():
    body = schema.body(CREATE_SPEC)
    if body["inspection_type"] == "AIR_MONITORING" and body["measured_organic_vapor_ppm"] is None:
        fail("ERR_INVALID_REQUEST", "measured_organic_vapor_ppm is required for air monitoring")
    if body["inspection_type"] == "AISLE_CLEARANCE" and body["measured_aisle_width_cm"] is None:
        fail("ERR_INVALID_REQUEST", "measured_aisle_width_cm is required for an aisle survey")

    # A storage unit named in the body still reports its own not-found error.
    u = db.units.get(body["storage_unit_id"])
    if u is None:
        fail("ERR_STORAGE_UNIT_NOT_FOUND")
    c = reference("containers", body["container_id"]) if body["container_id"] else None

    if c is not None:
        if c["storage_unit_id"] != u["id"]:
            fail("ERR_INVALID_STATE", "The named container does not stand in the inspected unit")
        if c["custody_state"] in ("VOIDED", "EMPTIED"):
            fail("ERR_INVALID_STATE", "The named container no longer holds waste")

    stamp = now()
    leak_definition = calc.LEAK_DEFINITION_PPM[u["air_emission_control_level"]]
    ppm = body["measured_organic_vapor_ppm"]
    leak_detected = bool(body["finding_code"] in LEAK_FINDING_CODES) or \
        (ppm is not None and D(ppm) >= D(leak_definition))
    aisle_compliant = None
    if body["inspection_type"] == "AISLE_CLEARANCE":
        aisle_compliant = D(body["measured_aisle_width_cm"]) >= D(calc.MIN_AISLE_WIDTH_CM)

    event = {
        "id": new_id(),
        "storage_unit_id": u["id"],
        "container_id": c["id"] if c is not None else None,
        "inspection_type": body["inspection_type"],
        "finding_code": body["finding_code"],
        "measured_organic_vapor_ppm": ppm,
        "measured_aisle_width_cm": body["measured_aisle_width_cm"],
        "performed_by_user_id": g.user_id,
        "inspected_at": stamp,
        "leak_detected": leak_detected,
        "aisle_compliant": aisle_compliant,
        "created_at": stamp,
    }
    insert("inspections", event)

    # Every inspection clears the unit's inspection_overdue flag.
    u["last_inspection_at"] = stamp

    if leak_detected:
        insert("repair_orders", {
            "id": new_id(),
            "storage_unit_id": u["id"],
            "container_id": c["id"] if c is not None else None,
            "source_inspection_event_id": event["id"],
            "leak_type": "CONTAINER_LEAK" if c is not None else "TANK_LEAK",
            "detected_at": stamp,
            "detected_ppm": ppm,
            "leak_definition_ppm": leak_definition,
            "first_attempt_due_at": add_days(stamp, calc.FIRST_ATTEMPT_DAYS),
            "repair_due_at": add_days(stamp, calc.REPAIR_DUE_DAYS),
            "delayed_due_at": None,
            "justification_code": "NONE",
            "status": "OPEN",
            "attempt_count": 0,
            "last_monitored_ppm": None,
            "created_at": stamp,
            "updated_at": stamp,
            "version": 1,
        })

    if c is not None and body["finding_code"] == "CONTAINER_LEAK":
        # CASCADE-1.
        c["compliance_state"] = "CONDEMNED"
        c["last_finding_code"] = "CONTAINER_LEAK"
        cascade.condemnation_cascade(c)
    elif c is not None and body["finding_code"] in DEFICIENCY_FINDING_CODES:
        if c["compliance_state"] == "COMPLIANT":
            c["compliance_state"] = "DEFICIENT"
            c["last_finding_code"] = body["finding_code"]
            cascade.deficiency_cascade(c)

    # A posture that is OPEN again releases anything the unit was holding.
    cascade.reconcile_unit(u)

    touch("units", u)
    return created(derive.project_inspection(event))


@bp.get("/tsdf/inspection-events/<eid>")
@endpoint(roles=READERS)
def get_inspection(eid):
    return ok(derive.project_inspection(load("inspections", eid)))


@bp.get("/tsdf/inspection-events")
@endpoint(roles=READERS)
def list_inspections():
    filters, limit, offset = schema.listing(
        filters=["storage_unit_id", "container_id", "inspection_type", "finding_code"],
        enums={"inspection_type": calc.INSPECTION_TYPES, "finding_code": calc.FINDING_CODES})
    rows = by_created_at(list(db.inspections.values()))
    for key in ("storage_unit_id", "container_id", "inspection_type", "finding_code"):
        if key in filters:
            rows = [e for e in rows if e[key] == filters[key]]
    return respond_list(rows, derive.project_inspection, limit, offset)
