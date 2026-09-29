"""Containers: placement and the two independent state dimensions."""

from decimal import Decimal

from flask import Blueprint

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import (by_created_at, check_assurance, check_profile_acceptable,
                           load, reference, respond_list)
from services import calc, cascade, derive
from services.tracking import touch
from util import D, new_id

bp = Blueprint("containers", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "ReceivingClerk", "TreatmentOperator", "RegulatoryInspector"]

CREATE_SPEC = {
    "manifest_line_id": {"type": "string", "required": True},
    "storage_unit_id": {"type": "string", "required": True},
    "container_type": {"type": "string", "required": True, "enum": calc.CONTAINER_TYPES},
    "capacity_kg": {"type": "number", "required": True, "gt": 0},
    "net_weight_kg": {"type": "number", "required": True, "gt": 0},
    "accumulation_start_date": {"type": "datetime", "required": True},
    "label_waste_codes": {"type": "array", "required": True, "items": {"type": "string"}},
    "label_hazard_class": {"type": "string", "required": True},
    "label_accumulation_start_marked": {"type": "bool", "required": True},
}


@bp.post("/tsdf/containers")
@endpoint(roles=["ReceivingClerk"], mutating=True)
def create_container():
    body = schema.body(CREATE_SPEC)

    ln = reference("lines", body["manifest_line_id"])
    u = reference("units", body["storage_unit_id"])
    m = derive.manifest(ln["manifest_id"])
    if m is None:
        fail("ERR_REFERENCE_NOT_FOUND")
    p = derive.profile(ln["waste_profile_id"]) if ln["waste_profile_id"] else None
    if p is None:
        fail("ERR_REFERENCE_NOT_FOUND", "The receipt line ships under no waste profile")

    # Priority 8: the unit must belong to the manifest's facility.
    if u["facility_id"] != m["facility_id"]:
        fail("ERR_FACILITY_SCOPE_MISMATCH")

    # Priority 9.
    if m["status"] == "REJECTED_RETURNED":
        fail("ERR_INVALID_STATE", "The shipment has been returned to its generator")
    if ln["line_status"] == "RETURNED":
        fail("ERR_INVALID_STATE", "The receipt line was returned to its generator")

    # Priority 10.
    if derive.unit_posture(u) not in ("OPEN", "RESTRICTED"):
        fail("ERR_UNIT_POSTURE_BLOCKED")

    # Priorities 14 and 15.
    check_profile_acceptable(p)

    # Priority 17: authorised class first, then the pairwise table.
    if p["compatibility_class"] not in u["allowed_compatibility_classes"]:
        fail("ERR_INCOMPATIBLE_SEGREGATION")
    for resident in derive.containers_of_unit(u["id"]):
        if resident["custody_state"] in ("VOIDED", "EMPTIED"):
            continue
        other = derive.profile(resident["waste_profile_id"])
        if other is None:
            continue
        if calc.incompatible(p["compatibility_class"], other["compatibility_class"]):
            fail("ERR_INCOMPATIBLE_SEGREGATION")

    # Priority 18.
    if set(body["label_waste_codes"]) != set(p["waste_codes"]):
        fail("ERR_LABEL_CODE_MISMATCH")
    if not body["label_hazard_class"].strip():
        fail("ERR_LABEL_INCOMPLETE")

    # Priority 19.
    if D(body["net_weight_kg"]) > D(calc.FILL_FRACTION_LIMIT) * D(body["capacity_kg"]):
        fail("ERR_CONTAINER_OVERFILLED")

    # Priority 22: a ten-day transfer unit is a pass-through, not a store.
    if u["unit_type"] == "TEN_DAY_TRANSFER":
        overdue = (now() - body["accumulation_start_date"]).total_seconds() // 86400 > calc.TEN_DAY_LIMIT_DAYS
        for resident in derive.containers_of_unit(u["id"]):
            if resident["custody_state"] in derive.OCCUPYING_STATES:
                overdue = overdue or derive.container_accumulation_days(resident) > calc.TEN_DAY_LIMIT_DAYS
        if overdue:
            fail("ERR_TEN_DAY_LIMIT_EXCEEDED")

    # Priority 29: the effective width is measured with the candidate included.
    projected = calc.effective_aisle_width(u["aisle_width_cm"], derive.unit_container_count(u) + 1,
                                           u["aisle_free_container_capacity"])
    if projected < D(calc.MIN_AISLE_WIDTH_CM):
        fail("ERR_AISLE_CLEARANCE_VIOLATION")

    # Priority 31.
    if D(body["net_weight_kg"]) > derive.line_remaining_mass(ln):
        fail("ERR_LINE_MASS_OVER_ALLOCATED")

    # Priority 34.
    occupied = derive.unit_stored_kg(u) + derive.unit_reserved_kg(u) + D(body["net_weight_kg"])
    if occupied > D(u["permitted_capacity_kg"]):
        fail("ERR_STORAGE_CAPACITY_EXCEEDED")

    # Priority 35.
    f = derive.facility(m["facility_id"])
    if f is None:
        fail("ERR_FACILITY_NOT_FOUND")
    check_assurance(f)

    stamp = now()
    row = {
        "id": new_id(),
        "manifest_line_id": ln["id"],
        "waste_profile_id": p["id"],
        "storage_unit_id": u["id"],
        "treatment_batch_id": None,
        "container_type": body["container_type"],
        "capacity_kg": body["capacity_kg"],
        "net_weight_kg": body["net_weight_kg"],
        "accumulation_start_date": body["accumulation_start_date"],
        "label_waste_codes": list(body["label_waste_codes"]),
        "label_hazard_class": body["label_hazard_class"],
        "label_accumulation_start_marked": body["label_accumulation_start_marked"],
        "custody_state": "FILLING",
        "compliance_state": "COMPLIANT",
        "last_finding_code": None,
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    insert("containers", row)
    cascade.reconcile_unit(u)
    return created(derive.project_container(row))


@bp.get("/tsdf/containers/<cid>")
@endpoint(roles=READERS)
def get_container(cid):
    return ok(derive.project_container(load("containers", cid)))


@bp.get("/tsdf/containers")
@endpoint(roles=READERS)
def list_containers():
    filters, limit, offset = schema.listing(
        filters=["manifest_line_id", "waste_profile_id", "storage_unit_id", "treatment_batch_id",
                 "custody_state", "compliance_state"],
        enums={"custody_state": calc.CUSTODY_STATES, "compliance_state": calc.COMPLIANCE_STATES})
    rows = by_created_at(list(db.containers.values()))
    for key in ("manifest_line_id", "waste_profile_id", "storage_unit_id", "treatment_batch_id",
                "custody_state", "compliance_state"):
        if key in filters:
            rows = [c for c in rows if c[key] == filters[key]]
    return respond_list(rows, derive.project_container, limit, offset)


@bp.post("/tsdf/containers/<cid>/custody-state")
@endpoint(roles=["ReceivingClerk", "TreatmentOperator"], mutating=True)
def set_custody_state(cid):
    body = schema.body({
        "to_custody_state": {"type": "string", "required": True, "enum": calc.CUSTODY_STATES},
        "reason_code": {"type": "string"},
    })
    c = load("containers", cid)
    current = c["custody_state"]
    target = body["to_custody_state"]

    if (current, target) == ("FILLING", "SEALED"):
        if not c["label_accumulation_start_marked"]:
            fail("ERR_LABEL_INCOMPLETE")
        c["custody_state"] = "SEALED"
    elif (current, target) == ("STAGED", "EMPTIED"):
        b = derive.batch(c["treatment_batch_id"]) if c["treatment_batch_id"] else None
        if b is None or b["status"] not in ("VERIFIED", "LDR_FAILED"):
            fail("ERR_INVALID_STATE", "The container's batch has not been through verification")
        if b["ldr_result"] == "FAIL":
            fail("ERR_LDR_STANDARD_NOT_MET")
        c["custody_state"] = "EMPTIED"
    elif current in ("FILLING", "SEALED") and target == "VOIDED":
        c["custody_state"] = "VOIDED"
    else:
        fail("ERR_INVALID_STATE", "Unsupported container custody transition")

    u = derive.unit(c["storage_unit_id"])
    if u is not None:
        cascade.reconcile_unit(u)
    touch("containers", c)
    return ok(derive.project_container(c))


@bp.post("/tsdf/containers/<cid>/compliance-state")
@endpoint(roles=["ComplianceManager"], mutating=True)
def set_compliance_state(cid):
    body = schema.body({
        "to_compliance_state": {"type": "string", "required": True, "enum": calc.COMPLIANCE_STATES},
        "finding_code": {"type": "string"},
    })
    c = load("containers", cid)
    current = c["compliance_state"]
    target = body["to_compliance_state"]

    if (current, target) == ("COMPLIANT", "DEFICIENT"):
        c["compliance_state"] = "DEFICIENT"
        c["last_finding_code"] = body["finding_code"]
        cascade.deficiency_cascade(c)
    elif (current, target) == ("DEFICIENT", "COMPLIANT"):
        c["compliance_state"] = "COMPLIANT"
        c["last_finding_code"] = None
        u = derive.unit(c["storage_unit_id"])
        if u is not None:
            cascade.reconcile_unit(u)
    elif current in ("COMPLIANT", "DEFICIENT") and target == "CONDEMNED":
        c["compliance_state"] = "CONDEMNED"
        c["last_finding_code"] = body["finding_code"]
        cascade.condemnation_cascade(c)
    elif (current, target) == ("CONDEMNED", "COMPLIANT"):
        for order in db.repair_orders.values():
            if order["container_id"] == cid and order["status"] != "REPAIRED":
                fail("ERR_INVALID_STATE", "An emission repair order on this container is still open")
        c["compliance_state"] = "COMPLIANT"
        c["last_finding_code"] = None
        u = derive.unit(c["storage_unit_id"])
        if u is not None:
            cascade.reconcile_unit(u)
    else:
        fail("ERR_INVALID_STATE", "Unsupported container compliance transition")

    touch("containers", c)
    return ok(derive.project_container(c))
