"""Treatment batches: scheduling, the operations capability, LDR verification."""

from decimal import Decimal

from flask import Blueprint, g

import schema
from db import db, insert, now
from errors import fail
from middleware import endpoint
from response import created, ok
from routes.common import by_created_at, check_permit_active, load, reference, respond_list
from services import calc, cascade, derive
from services.tracking import touch
from util import D, new_id, qd

bp = Blueprint("treatment_batches", __name__)

READERS = ["PlatformAdmin", "ComplianceManager", "TreatmentOperator", "RegulatoryInspector"]

CREATE_SPEC = {
    "facility_id": {"type": "string", "required": True},
    "storage_unit_id": {"type": "string", "required": True},
    "treatment_method": {"type": "string", "required": True, "enum": calc.TREATMENT_METHODS},
    "container_ids": {"type": "array", "required": True, "non_empty": True,
                      "items": {"type": "string"}},
    "window_start": {"type": "datetime", "required": True},
    "window_end": {"type": "datetime", "required": True},
}

OPERATION_SPEC = {
    "action": {"type": "string", "required": True,
               "enum": ["START", "COMPLETE", "ABORT", "RETREAT_RESET"]},
    "residue_mass_kg": {"type": "number", "ge": 0},
    "residue_constituent_ppm": {"type": "number", "ge": 0},
    "residue_flash_point_c": {"type": "number"},
    "reason_code": {"type": "string"},
}


def _ldr_family(b):
    p = derive.dominant_profile(b)
    return p["ldr_subcategory"] if p is not None else "NONE"


def _unstage(b, clear_batch_id):
    for c in derive.batch_containers(b):
        if c["custody_state"] == "STAGED":
            c["custody_state"] = "SEALED"
            if clear_batch_id:
                c["treatment_batch_id"] = None


@bp.post("/tsdf/treatment-batches")
@endpoint(roles=["TreatmentOperator"], mutating=True)
def create_batch():
    body = schema.body(CREATE_SPEC)
    if body["window_end"] <= body["window_start"]:
        fail("ERR_INVALID_REQUEST", "window_end must be strictly later than window_start")

    f = reference("facilities", body["facility_id"])
    u = reference("units", body["storage_unit_id"])
    ordered = []
    for cid in body["container_ids"]:
        c = reference("containers", cid)
        if c["id"] not in [existing["id"] for existing in ordered]:
            ordered.append(c)

    # Priority 8.
    if u["facility_id"] != f["id"]:
        fail("ERR_FACILITY_SCOPE_MISMATCH")

    # Priority 9: each container must be sealed, compliant and standing in the unit.
    for c in ordered:
        if c["custody_state"] != "SEALED":
            fail("ERR_INVALID_STATE", "A listed container is not sealed")
        if c["compliance_state"] != "COMPLIANT":
            fail("ERR_INVALID_STATE", "A listed container is not compliant")
        if c["storage_unit_id"] != u["id"]:
            fail("ERR_INVALID_STATE", "A listed container does not stand in the target unit")

    # Priority 10: scheduling demands a fully open unit.
    if derive.unit_posture(u) != "OPEN":
        fail("ERR_UNIT_POSTURE_BLOCKED")
    # Priority 11 then 20.
    check_permit_active(f)
    if body["treatment_method"] not in f["permitted_methods"]:
        fail("ERR_METHOD_NOT_PERMITTED")

    # Priority 22.
    if u["unit_type"] == "TEN_DAY_TRANSFER":
        for resident in derive.containers_of_unit(u["id"]):
            if resident["custody_state"] in derive.OCCUPYING_STATES and \
                    derive.container_accumulation_days(resident) > calc.TEN_DAY_LIMIT_DAYS:
                fail("ERR_TEN_DAY_LIMIT_EXCEEDED")

    input_mass = qd(sum((D(c["net_weight_kg"]) for c in ordered), Decimal(0)), 3)
    dominant = sorted(ordered, key=lambda c: (-D(c["net_weight_kg"]), c["created_at"], c["_seq"]))[0]
    dominant_p = derive.profile(dominant["waste_profile_id"])
    dominant_class = dominant_p["compatibility_class"] if dominant_p is not None else None

    # Priority 27: unit-level pairwise half-open windows with the decontamination buffer.
    for other in derive.batches_of_unit(u["id"]):
        if other["status"] not in calc.NON_TERMINAL_BATCH_STATUSES:
            continue
        buffer_minutes = 0 if other["dominant_compatibility_class"] == dominant_class \
            else calc.WINDOW_BUFFER_MINUTES
        if calc.windows_overlap(body["window_start"], body["window_end"],
                                other["window_start"], other["window_end"], buffer_minutes):
            fail("ERR_TREATMENT_WINDOW_CONFLICT")

    # Priority 28: facility-level aggregate over closed intervals.
    concurrent = 0
    for other in derive.batches_of_facility(f["id"]):
        if other["status"] not in calc.NON_TERMINAL_BATCH_STATUSES:
            continue
        if other["window_start"] <= body["window_end"] and other["window_end"] >= body["window_start"]:
            concurrent += 1
    if concurrent >= int(f["max_concurrent_treatment_batches"]):
        fail("ERR_FACILITY_CONCURRENCY_EXCEEDED")

    # Priority 34.
    if derive.unit_stored_kg(u) + derive.unit_reserved_kg(u) + input_mass > D(u["permitted_capacity_kg"]):
        fail("ERR_STORAGE_CAPACITY_EXCEEDED")

    stamp = now()
    b = {
        "id": new_id(),
        "facility_id": f["id"],
        "storage_unit_id": u["id"],
        "treatment_method": body["treatment_method"],
        "container_ids": [c["id"] for c in ordered],
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "dominant_compatibility_class": dominant_class,
        "input_mass_kg": input_mass,
        "estimated_treatment_liability_cents": calc.treatment_liability_cents(input_mass),
        "status": "PLANNED",
        "residue_constituent_ppm": None,
        "residue_flash_point_c": None,
        "residue_mass_kg": 0,
        "verification_sample_ppm": None,
        "ldr_standard_ppm": None,
        "ldr_result": "PENDING",
        "completed_by_user_id": None,
        "verified_by_user_id": None,
        "retreat_count": 0,
        "held_reason_code": "NONE",
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    insert("batches", b)
    for c in ordered:
        c["custody_state"] = "STAGED"
        c["treatment_batch_id"] = b["id"]
    cascade.reconcile_unit(u)
    return created(derive.project_batch(b))


@bp.get("/tsdf/treatment-batches/<bid>")
@endpoint(roles=READERS)
def get_batch(bid):
    return ok(derive.project_batch(load("batches", bid)))


@bp.get("/tsdf/treatment-batches")
@endpoint(roles=READERS)
def list_batches():
    filters, limit, offset = schema.listing(
        filters=["facility_id", "storage_unit_id", "status", "ldr_result"],
        enums={"status": calc.BATCH_STATUSES, "ldr_result": calc.LDR_RESULTS})
    rows = by_created_at(list(db.batches.values()))
    for key in ("facility_id", "storage_unit_id", "status", "ldr_result"):
        if key in filters:
            rows = [b for b in rows if b[key] == filters[key]]
    return respond_list(rows, derive.project_batch, limit, offset)


@bp.post("/tsdf/treatment-batches/<bid>/operations")
@endpoint(roles=["TreatmentOperator"], mutating=True)
def batch_operation(bid):
    body = schema.body(OPERATION_SPEC)
    action = body["action"]
    b = load("batches", bid)
    u = derive.unit(b["storage_unit_id"])
    f = derive.facility(b["facility_id"])

    if action == "START":
        if b["status"] != "PLANNED":
            fail("ERR_INVALID_STATE", "Only a planned batch may be started")
        if u is None or derive.unit_posture(u) != "OPEN":
            fail("ERR_UNIT_POSTURE_BLOCKED")
        if f is None:
            fail("ERR_PERMIT_NOT_ACTIVE")
        check_permit_active(f)
        if b["treatment_method"] not in f["permitted_methods"]:
            fail("ERR_METHOD_NOT_PERMITTED")
        if derive.unit_inspection_overdue(u):
            fail("ERR_INSPECTION_OVERDUE")
        if now() < b["window_start"]:
            fail("ERR_INVALID_STATE", "The treatment window has not opened yet")
        b["status"] = "IN_TREATMENT"

    elif action == "COMPLETE":
        if b["status"] != "IN_TREATMENT":
            fail("ERR_INVALID_STATE", "Only a batch in treatment may be completed")
        if _ldr_family(b) == "D001_IGNITABLE" and body["residue_flash_point_c"] is None:
            fail("ERR_INVALID_REQUEST", "residue_flash_point_c is required for an ignitable residue")
        residue = D(body["residue_mass_kg"] or 0)
        if residue > D(b["input_mass_kg"]):
            fail("ERR_MASS_BALANCE_INVALID")
        b["residue_mass_kg"] = qd(residue, 3)
        b["residue_constituent_ppm"] = body["residue_constituent_ppm"]
        b["residue_flash_point_c"] = body["residue_flash_point_c"]
        b["completed_by_user_id"] = g.user_id
        b["ldr_result"] = "PENDING"
        b["status"] = "TREATED"

    elif action == "ABORT":
        if b["status"] not in ("PLANNED", "HELD", "IN_TREATMENT"):
            fail("ERR_INVALID_STATE", "The batch cannot be aborted from its current status")
        _unstage(b, clear_batch_id=True)
        b["status"] = "ABORTED"
        b["held_reason_code"] = "NONE"

    else:
        if b["status"] != "LDR_FAILED":
            fail("ERR_INVALID_STATE", "Only a batch that failed its LDR standard may be reset")
        if int(b["retreat_count"]) > 1:
            fail("ERR_INVALID_STATE", "The re-treatment ceiling has been reached")
        _unstage(b, clear_batch_id=False)
        b["retreat_count"] = int(b["retreat_count"]) + 1
        b["ldr_result"] = "PENDING"
        b["residue_mass_kg"] = 0
        b["residue_constituent_ppm"] = None
        b["residue_flash_point_c"] = None
        b["verification_sample_ppm"] = None
        b["verified_by_user_id"] = None
        b["status"] = "PLANNED"

    if u is not None:
        cascade.reconcile_unit(u)
    touch("batches", b)
    return ok(derive.project_batch(b))


@bp.post("/tsdf/treatment-batches/<bid>/ldr-verification")
@endpoint(roles=["ComplianceManager"], mutating=True)
def ldr_verification(bid):
    body = schema.body({
        "verification_sample_ppm": {"type": "number", "ge": 0},
        "verification_note": {"type": "string"},
    })
    b = load("batches", bid)
    if b["status"] != "TREATED":
        fail("ERR_INVALID_STATE", "Only a treated batch may be verified")
    if b["completed_by_user_id"] is not None and b["completed_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    family = _ldr_family(b)
    b["verification_sample_ppm"] = body["verification_sample_ppm"]

    if family == "NONE":
        b["ldr_standard_ppm"] = None
        passed = True
    elif family == "D001_IGNITABLE":
        b["ldr_standard_ppm"] = None
        flash = b["residue_flash_point_c"]
        passed = flash is not None and D(flash) >= D(calc.LDR_FLASH_POINT_MIN_C)
    else:
        standard = calc.LDR_CONCENTRATION_STANDARD_PPM[family]
        b["ldr_standard_ppm"] = standard
        if body["verification_sample_ppm"] is None:
            fail("ERR_INVALID_REQUEST", "verification_sample_ppm is required for this LDR family")
        passed = D(body["verification_sample_ppm"]) <= D(standard)

    b["verified_by_user_id"] = g.user_id
    b["ldr_result"] = "PASS" if passed else "FAIL"
    b["status"] = "VERIFIED" if passed else "LDR_FAILED"

    u = derive.unit(b["storage_unit_id"])
    if u is not None:
        cascade.reconcile_unit(u)
    touch("batches", b)
    return ok(derive.project_batch(b))
