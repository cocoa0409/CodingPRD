"""Complaint endpoints (PRD §3.7): intake, adjudication with its cascade, close."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_COMPLAINT_NOT_FOUND,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_INVALID_TRANSITION,
    ERR_REQUEST_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_VALIDATION,
)
from middleware import authorized, check_liaison_owns_department
from response import success_object
from routes.helpers import get_one, list_endpoint
from services.core import (
    REMEDIATION_WINDOW,
    recompute_interpreter_rating,
    touch,
)
from services.serializers import serialize_complaint
from util import CLOCK, fmt_iso, new_id, next_seq
from validate import (
    get_body,
    opt_nullable_str,
    reject_unknown_fields,
    req_enum,
    req_str,
    require_path,
)

bp = Blueprint("complaints", __name__)

CATEGORIES = {
    "NO_INTERPRETER_AVAILABLE", "POOR_QUALITY", "CONFIDENTIALITY_BREACH",
    "NOTICE_MISSING", "OTHER",
}
OUTCOMES = {"SUBSTANTIATED", "DISMISSED"}
REMEDIES = {"NONE", "REFUND"}


@bp.post("/complaints")
def create_complaint():
    caller = authorized(["DepartmentLiaison", "ComplianceOfficer"])
    body = get_body()
    check_liaison_owns_department(caller, body.get("department_id"))
    reject_unknown_fields(body, {"department_id", "interpretation_request_id", "category", "description"})
    department_id = req_str(body, "department_id")
    interpretation_request_id = opt_nullable_str(body, "interpretation_request_id")
    category = req_enum(body, "category", CATEGORIES)
    description = req_str(body, "description")

    require_path("departments", department_id, ERR_DEPARTMENT_NOT_FOUND)
    if interpretation_request_id is not None:
        require_path("interpretation_requests", interpretation_request_id, ERR_REQUEST_NOT_FOUND)

    now = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "department_id": department_id,
        "interpretation_request_id": interpretation_request_id,
        "category": category,
        "description": description,
        "recorded_by_user_id": caller.user_id,
        "status": "RECEIVED",
        "adjudicated_by_user_id": None,
        "adjudicated_at": None,
        "remedy": None,
        "remediation_due_at": None,
        "resolution_note": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["complaints"][rec["id"]] = rec
    return success_object(serialize_complaint(rec), status=201)


@bp.get("/complaints")
def list_complaints():
    filters = {
        "department_id": request.args.get("department_id"),
        "interpretation_request_id": request.args.get("interpretation_request_id"),
        "status": request.args.get("status"),
    }
    return list_endpoint("complaints", serialize_complaint, filters)


@bp.get("/complaints/<rid>")
def get_complaint(rid):
    return get_one("complaints", rid, ERR_COMPLAINT_NOT_FOUND, serialize_complaint)


@bp.post("/complaints/<rid>/adjudicate")
def adjudicate_complaint(rid):
    caller = authorized(["ComplianceOfficer"])
    body = get_body()
    reject_unknown_fields(body, {"outcome", "remedy"})
    outcome = req_enum(body, "outcome", OUTCOMES)
    remedy = req_enum(body, "remedy", REMEDIES) if body.get("remedy") is not None else None

    rec = require_path("complaints", rid, ERR_COMPLAINT_NOT_FOUND)
    if rec["status"] != "RECEIVED":
        raise_error(ERR_INVALID_TRANSITION, "only a RECEIVED complaint may be adjudicated")
    if caller.user_id == rec["recorded_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                    "the officer who recorded a complaint may not adjudicate it")

    linked = None
    if rec["interpretation_request_id"] is not None:
        linked = db["interpretation_requests"].get(rec["interpretation_request_id"])
    if outcome == "SUBSTANTIATED" and remedy == "REFUND":
        if linked is None or linked["status"] != "COMPLETED":
            raise_error(ERR_VALIDATION, "remedy REFUND requires a linked COMPLETED request")

    now = CLOCK.now()
    rec["adjudicated_by_user_id"] = caller.user_id
    rec["adjudicated_at"] = fmt_iso(now)

    if outcome == "DISMISSED":
        rec["status"] = "DISMISSED"
        rec["remedy"] = remedy or "NONE"
        touch(rec)
        return success_object(serialize_complaint(rec))

    # SUBSTANTIATED: stamps, remediation deadline, then the cascade.
    rec["status"] = "SUBSTANTIATED"
    rec["remedy"] = remedy or "NONE"
    rec["remediation_due_at"] = fmt_iso(now + REMEDIATION_WINDOW)
    touch(rec)

    # Link 1a: department compliance takes the -150 event (derivational replay).
    dept = db["departments"].get(rec["department_id"])
    if dept is not None:
        # Link 1b: NOTICE_MISSING flips signage to DEFICIENT.
        if rec["category"] == "NOTICE_MISSING":
            dept["signage_status"] = "DEFICIENT"
        touch(dept)

    # Link 1c: linked session costs its interpreter a -200 rating event;
    # links 2-4: recomputation below 600 auto-suspends and cancels assignments.
    if linked is not None and linked["interpreter_id"] is not None:
        interp = db["interpreters"].get(linked["interpreter_id"])
        if interp is not None:
            recompute_interpreter_rating(interp)
            touch(interp)

    # REFUND remedy: claw the request's cost out of both ledgers and drop its
    # minutes (all derivational once the flag flips).
    if remedy == "REFUND" and linked is not None:
        linked["refund_clawed_back"] = True
        touch(linked)
        if dept is not None:
            touch(dept)
        contract = db["vendor_contracts"].get(linked["_contract_id"])
        if contract is not None:
            touch(contract)
    return success_object(serialize_complaint(rec))


@bp.post("/complaints/<rid>/close")
def close_complaint(rid):
    authorized(["ComplianceOfficer"])
    body = get_body()
    reject_unknown_fields(body, {"resolution_note"})
    resolution_note = body.get("resolution_note")
    if resolution_note is None or not isinstance(resolution_note, str) or resolution_note.strip() == "":
        raise_error(ERR_VALIDATION, "resolution_note is required")

    rec = require_path("complaints", rid, ERR_COMPLAINT_NOT_FOUND)
    if rec["status"] != "SUBSTANTIATED":
        raise_error(ERR_INVALID_TRANSITION, "only a SUBSTANTIATED complaint may be closed")

    from util import parse_iso
    now = CLOCK.now()
    rec["status"] = "RESOLVED"
    rec["resolution_note"] = resolution_note
    rec["closed_at"] = fmt_iso(now)
    touch(rec)
    # On-time close restores +100 (derivational replay); late close restores nothing.
    if rec["remediation_due_at"] and parse_iso(rec["closed_at"]) <= parse_iso(rec["remediation_due_at"]):
        dept = db["departments"].get(rec["department_id"])
        if dept is not None:
            touch(dept)
    return success_object(serialize_complaint(rec))
