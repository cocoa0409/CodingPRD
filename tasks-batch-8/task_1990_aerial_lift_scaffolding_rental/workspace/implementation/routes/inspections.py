"""Inspection records: submit, list, read, certify, reject."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import get_context, require_roles
from response import ok, created, paginate
from services import calc, domain
from validation import validate_body

bp = Blueprint("inspections", __name__)


def _load_record(rid):
    record = store.inspections.get(rid)
    if record is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Inspection record not found")
    return record


def _decide(rid, decision):
    """Shared certification/rejection pipeline (segregation of duties)."""
    uid, role = get_context()
    require_roles(["BranchManager"])
    record = _load_record(rid)
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Inspection record is not SUBMITTED")
    if uid == record["inspector_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 422,
                       "The certifier/rejecter must not be the submitting inspector")
    record["certified_by"] = uid
    record["certified_at"] = db.logical_stamp()
    record["status"] = decision
    db.touch(record)
    return uid, record


@bp.post("/inspection-records")
def create_inspection():
    uid, role = get_context()
    require_roles(["YardTechnician"])
    body = validate_body({
        "unit_id": ("string", True),
        "inspection_date": ("date", True),
        "ansi_standard_ref": ("string", True),
        "result": ("enum", True, {"values": ["PASS", "FAIL"]}),
    })
    if body["unit_id"] not in store.units:
        raise ApiError("ERR_NOT_FOUND", 404, "Equipment unit not found")
    record = db.new_common({
        "id": db.new_id(),
        "unit_id": body["unit_id"],
        "inspector_id": uid,
        "inspection_date": body["inspection_date"],
        "ansi_standard_ref": body["ansi_standard_ref"],
        "result": body["result"],
        "status": "SUBMITTED",
        "certified_by": None,
        "certified_at": None,
    })
    store.inspections[record["id"]] = record
    return created(domain.view_inspection(record))


@bp.get("/inspection-records")
def list_inspections():
    uid, role = get_context()
    require_roles(["BranchManager", "YardTechnician"])
    rows = [domain.view_inspection(r) for r in store.inspections.values()]
    rows = paginate.filter(rows, "unit_id")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/inspection-records/<rid>")
def get_inspection(rid):
    uid, role = get_context()
    require_roles(["BranchManager", "YardTechnician"])
    record = _load_record(rid)
    return ok(domain.view_inspection(record))


@bp.post("/inspection-records/<rid>/certify")
def certify_inspection(rid):
    uid, record = _decide(rid, "CERTIFIED")
    unit = store.units[record["unit_id"]]
    if record["result"] == "PASS":
        # Rewrite the inspection calendar; release quarantine if quarantined.
        unit["last_annual_inspection_date"] = record["inspection_date"]
        if unit["status"] == "QUARANTINED":
            unit["status"] = "AVAILABLE"
        db.touch(unit)
    else:  # FAIL
        if unit["status"] == "AVAILABLE":
            unit["status"] = "QUARANTINED"
        # Cancel every RESERVED line on the unit (OUT_ON_RENT/OFF_RENT unaffected).
        for line in store.lines.values():
            if line["unit_id"] == unit["id"] and line["status"] == "RESERVED":
                line["status"] = "CANCELLED"
                db.touch(line)
                contract = store.contracts.get(line["contract_id"])
                if contract is not None:
                    db.touch(contract)  # rental_subtotal recompute per cancelled line
                    customer = store.customers.get(contract["customer_id"])
                    if customer is not None:
                        calc.maybe_suspend(customer)
        db.touch(unit)
    return ok(domain.view_inspection(record))


@bp.post("/inspection-records/<rid>/reject")
def reject_inspection(rid):
    uid, record = _decide(rid, "REJECTED")
    return ok(domain.view_inspection(record))
