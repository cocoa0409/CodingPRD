import uuid
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_SPLICE_EXISTS,
    ERR_CROSS_REFERENCE_MISMATCH, ERR_BUDGET_EXCEEDED, ERR_CURING_INCOMPLETE,
    ERR_RETEST_REQUIRED,
)
from helpers import (
    body_dict, req_str, req_int, req_enum, get_or_404, serialize,
    serialize_list, paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import calc
from services import workflow

bp = Blueprint("splices", __name__)


@bp.post("/cable-diagnostics/repair-splices")
def create_splice():
    authenticate(["FaultCrewLead"])
    body = body_dict()
    fault_record_id = req_str(body, "fault_record_id")
    excavation_order_id = req_str(body, "excavation_order_id")
    splice_type = req_enum(body, "splice_type", calc.SPLICE_TYPES)
    cost_cents = req_int(body, "cost_cents")
    if cost_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "cost_cents must be > 0")

    fault = get_or_404(db.faults, fault_record_id, "FaultRecord")
    excavation = get_or_404(db.excavations, excavation_order_id, "ExcavationOrder")

    if excavation["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Excavation must be IN_PROGRESS")
    for s in db.splices.values():
        if s["fault_record_id"] == fault_record_id and s["status"] in workflow.OPEN_SPLICE_STATES:
            raise ApiError(ERR_SPLICE_EXISTS, 409, "An open splice already exists for the fault")
    if excavation["fault_record_id"] != fault_record_id:
        raise ApiError(ERR_CROSS_REFERENCE_MISMATCH, 422, "Excavation belongs to a different fault")

    job = db.jobs[fault["test_job_id"]]
    estimate = job["estimate_cents"] or 0
    if estimate + job["committed_cost_cents"] + cost_cents > job["approved_budget_cents"]:
        raise ApiError(ERR_BUDGET_EXCEEDED, 422, "Committed costs would exceed the approved budget")

    now = db.now()
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "fault_record_id": fault_record_id,
        "excavation_order_id": excavation_order_id,
        "splice_type": splice_type,
        "cost_cents": cost_cents,
        "status": "PLANNED",
        "cure_started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.splices[rec["id"]] = rec
    job["committed_cost_cents"] += cost_cents
    workflow.touch(job)
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/repair-splices/<sid>")
def get_splice(sid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.splices, sid, "RepairSplice")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/repair-splices")
def list_splices():
    authenticate(ALL_ROLES)
    recs = list(db.splices.values())
    fault_id = request.args.get("fault_record_id")
    if fault_id is not None:
        recs = [s for s in recs if s["fault_record_id"] == fault_id]
    exc_id = request.args.get("excavation_order_id")
    if exc_id is not None:
        recs = [s for s in recs if s["excavation_order_id"] == exc_id]
    status = request.args.get("status")
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/repair-splices/<sid>/start")
def start_splice(sid):
    authenticate(["FaultCrewLead"])
    rec = get_or_404(db.splices, sid, "RepairSplice")
    if rec["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PLANNED splice can be started")
    fault = db.faults[rec["fault_record_id"]]
    if fault["status"] != "EXCAVATING":
        raise ApiError(ERR_INVALID_STATE, 409, "Fault must be EXCAVATING to start splicing")
    rec["status"] = "SPLICING"
    workflow.touch(rec)
    fault["status"] = "REPAIRING"
    workflow.touch(fault)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/repair-splices/<sid>/cure")
def cure_splice(sid):
    authenticate(["FaultCrewLead"])
    rec = get_or_404(db.splices, sid, "RepairSplice")
    if rec["status"] != "SPLICING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SPLICING splice can begin curing")
    rec["status"] = "CURING"
    rec["cure_started_at"] = db.now()
    workflow.touch(rec)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/repair-splices/<sid>/finish-curing")
def finish_curing(sid):
    authenticate(["FaultCrewLead"])
    rec = get_or_404(db.splices, sid, "RepairSplice")
    if rec["status"] != "CURING":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a CURING splice can finish curing")
    if db.now() < rec["cure_started_at"] + timedelta(hours=24):
        raise ApiError(ERR_CURING_INCOMPLETE, 409, "Cure requires at least 24 hours")
    rec["status"] = "COMPLETED"
    rec["completed_at"] = db.now()
    workflow.touch(rec)
    fault = db.faults[rec["fault_record_id"]]
    if fault["status"] == "REPAIRING":
        fault["status"] = "REPAIRED"
        workflow.touch(fault)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/repair-splices/<sid>/accept")
def accept_splice(sid):
    authenticate(["NetworkPlanner"])
    rec = get_or_404(db.splices, sid, "RepairSplice")
    if rec["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a COMPLETED splice can be accepted")
    qualifying = any(
        s["retest_of_fault_id"] == rec["fault_record_id"]
        and s["status"] == "ACCEPTED"
        and s["verdict"] == "PASS"
        and rec["completed_at"] is not None
        and s["created_at"] > rec["completed_at"]
        for s in db.series.values()
    )
    if not qualifying:
        raise ApiError(ERR_RETEST_REQUIRED, 409, "No qualifying passing re-test created after completed_at")
    rec["status"] = "ACCEPTED"
    workflow.touch(rec)
    fault = db.faults[rec["fault_record_id"]]
    if fault["status"] == "RETESTING":
        workflow.fault_closed(fault)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/repair-splices/<sid>/reject")
def reject_splice(sid):
    authenticate(["NetworkPlanner"])
    rec = get_or_404(db.splices, sid, "RepairSplice")
    if rec["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a COMPLETED splice can be rejected")
    rec["status"] = "REJECTED"
    workflow.touch(rec)
    fault = db.faults[rec["fault_record_id"]]
    if fault["status"] in ("REPAIRED", "RETESTING"):
        fault["status"] = "REOPENED"
        workflow.touch(fault)
    return success(serialize(rec))
