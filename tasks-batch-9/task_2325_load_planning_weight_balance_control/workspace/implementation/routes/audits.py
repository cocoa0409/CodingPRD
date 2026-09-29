"""Post-flight load audits and discrepancy investigation (PRD §3.9)."""
from flask import Blueprint

import calc
import db
import middleware
import resolve
import response
import validate
from calc import D
from errors import (
    ERR_AUDIT_INVALID_STATE,
    ERR_AUDIT_SEGREGATION_CONFLICT,
    ERR_FINDING_NOTE_REQUIRED,
    ERR_FLIGHT_INVALID_STATE,
    ERR_NO_ACCEPTED_SHEET,
    fail,
)
from middleware import ANY_ROLE, authorize
from services import balance

bp = Blueprint("audits", __name__)

BASES = ("DOCUMENTED_BASIS", "FINAL_BASIS")
AUDITABLE_FLIGHT_STATUSES = ("LOAD_CONTROLLED", "DEPARTED", "CLOSED")
DIRECT_CLOSE_SEVERITIES = ("NONE", "MINOR")
INVESTIGABLE_SEVERITIES = ("MAJOR", "CRITICAL")
PAX_KINDS = ("PAX_ADD", "PAX_REMOVE")
BAG_KINDS = ("BAG_ADD", "BAG_REMOVE")
CARGO_KINDS = ("CARGO_OFFLOAD",)


@bp.post("/load-audits")
@authorize("AuditInspector")
def open_load_audit():
    payload = validate.body()
    row = {
        "flight_id": validate.req_str(payload, "flight_id"),
        "basis": validate.req_enum(payload, "basis", BASES),
        "actual_pax_weight_kg": validate.req_num(payload, "actual_pax_weight_kg", ge=0),
        "actual_bag_weight_kg": validate.req_num(payload, "actual_bag_weight_kg", ge=0),
        "actual_cargo_weight_kg": validate.req_num(payload, "actual_cargo_weight_kg", ge=0),
        "status": "OPEN",
        "closed_by_user_id": None,
        "finding_note": None,
    }

    flight = resolve.flight(row["flight_id"])
    if flight["status"] not in AUDITABLE_FLIGHT_STATUSES:
        fail(ERR_FLIGHT_INVALID_STATE)

    plan = balance.audit_reference_plan(flight["id"])
    sheet = balance.accepted_sheet_of(plan)
    if row["basis"] == "FINAL_BASIS" and sheet is None:
        fail(ERR_NO_ACCEPTED_SHEET)

    pax_basis, bag_basis, cargo_basis = balance.documented_figures(flight["id"], plan)
    if row["basis"] == "FINAL_BASIS":
        pax_basis = calc.r2(pax_basis + balance.lmc_class_sum(sheet, PAX_KINDS))
        bag_basis = calc.r2(bag_basis + balance.lmc_class_sum(sheet, BAG_KINDS))
        cargo_basis = calc.r2(cargo_basis + balance.lmc_class_sum(sheet, CARGO_KINDS))

    pax_delta = calc.r2(D(row["actual_pax_weight_kg"]) - pax_basis)
    bag_delta = calc.r2(D(row["actual_bag_weight_kg"]) - bag_basis)
    cargo_delta = calc.r2(D(row["actual_cargo_weight_kg"]) - cargo_basis)
    total = calc.r2(abs(pax_delta) + abs(bag_delta) + abs(cargo_delta))

    row["pax_delta_kg"] = float(pax_delta)
    row["bag_delta_kg"] = float(bag_delta)
    row["cargo_delta_kg"] = float(cargo_delta)
    row["total_absolute_discrepancy_kg"] = float(total)
    row["severity"] = calc.audit_severity(total)
    return response.object_response(db.public(db.insert(db.load_audits, row)), 201)


@bp.get("/load-audits/<row_id>")
@authorize(*ANY_ROLE)
def read_load_audit(row_id):
    return response.object_response(db.public(resolve.load_audit(row_id)))


@bp.post("/load-audits/<row_id>/investigate")
@authorize("AuditInspector")
def investigate_load_audit(row_id):
    audit = resolve.load_audit(row_id)
    if audit["status"] != "OPEN" or audit["severity"] not in INVESTIGABLE_SEVERITIES:
        fail(ERR_AUDIT_INVALID_STATE)
    audit["status"] = "INVESTIGATING"
    db.touch(audit)
    return response.object_response(db.public(audit))


@bp.post("/load-audits/<row_id>/close")
@authorize("AuditInspector")
def close_load_audit(row_id):
    payload = validate.body()
    note = validate.opt_str(payload, "finding_note")

    audit = resolve.load_audit(row_id)
    if audit["status"] == "OPEN":
        if audit["severity"] not in DIRECT_CLOSE_SEVERITIES:
            fail(ERR_AUDIT_INVALID_STATE)
    elif audit["status"] != "INVESTIGATING":
        fail(ERR_AUDIT_INVALID_STATE)

    actor = middleware.current_user_id()
    for declaration in db.flight_declarations(audit["flight_id"]):
        if declaration.get("accepted_by_user_id") and declaration["accepted_by_user_id"] == actor:
            fail(ERR_AUDIT_SEGREGATION_CONFLICT)

    if note is None or not note.strip():
        fail(ERR_FINDING_NOTE_REQUIRED)

    audit["finding_note"] = note
    audit["status"] = "CLOSED"
    audit["closed_by_user_id"] = actor
    db.touch(audit)
    return response.object_response(db.public(audit))
