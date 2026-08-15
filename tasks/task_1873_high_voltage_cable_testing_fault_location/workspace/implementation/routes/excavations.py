import uuid

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_DIG_OUTSIDE_OUTAGE,
    ERR_CORRIDOR_VIOLATION, ERR_DIG_WINDOW_OVERLAP, ERR_EXCAVATION_EXISTS,
    ERR_BUDGET_EXCEEDED, ERR_WINDOW_NOT_ACTIVE, ERR_SPLICE_NOT_CURING,
)
from helpers import (
    body_dict, req_str, req_int, req_num, req_dt, get_or_404, serialize,
    serialize_list, paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import workflow
from util import dec as dec_num

bp = Blueprint("excavations", __name__)


@bp.post("/cable-diagnostics/excavation-orders")
def create_excavation():
    authenticate(["FaultCrewLead"])
    body = body_dict()
    fault_record_id = req_str(body, "fault_record_id")
    target_location_m = req_num(body, "target_location_m")
    dig_start = req_dt(body, "dig_start")
    dig_end = req_dt(body, "dig_end")
    if dig_end <= dig_start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "dig_end must be strictly after dig_start")
    permit_ref = req_str(body, "permit_ref")
    cost_cents = req_int(body, "cost_cents")
    if cost_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "cost_cents must be > 0")

    fault = get_or_404(db.faults, fault_record_id, "FaultRecord")

    if fault["status"] not in ("PINPOINTED", "EXCAVATING", "REPAIRING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Fault must be PINPOINTED, EXCAVATING or REPAIRING")

    job = db.jobs[fault["test_job_id"]]
    window = db.windows[job["outage_window_id"]]
    if dig_start < window["window_start"] or dig_end > window["window_end"]:
        raise ApiError(ERR_DIG_OUTSIDE_OUTAGE, 409, "Dig interval is not contained in the outage window")

    target = dec_num(target_location_m)
    if target < fault["corridor_start_m"] or target > fault["corridor_end_m"]:
        raise ApiError(ERR_CORRIDOR_VIOLATION, 409, "target_location_m lies outside the pinpoint corridor")

    others = [
        e for e in db.excavations.values()
        if e["fault_record_id"] == fault_record_id and e["status"] != "CANCELLED"
    ]
    for e in others:
        if dig_start < e["dig_end"] and e["dig_start"] < dig_end:
            raise ApiError(ERR_DIG_WINDOW_OVERLAP, 409, "Dig interval overlaps another excavation of this fault")
    if others:
        raise ApiError(ERR_EXCAVATION_EXISTS, 409, "A non-cancelled excavation already exists for this fault")

    estimate = job["estimate_cents"] or 0
    if estimate + job["committed_cost_cents"] + cost_cents > job["approved_budget_cents"]:
        raise ApiError(ERR_BUDGET_EXCEEDED, 422, "Committed costs would exceed the approved budget")

    now = db.now()
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "fault_record_id": fault_record_id,
        "target_location_m": target_location_m,
        "dig_start": dig_start,
        "dig_end": dig_end,
        "permit_ref": permit_ref,
        "cost_cents": cost_cents,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.excavations[rec["id"]] = rec
    job["committed_cost_cents"] += cost_cents
    workflow.touch(job)
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/excavation-orders/<eid>")
def get_excavation(eid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.excavations, eid, "ExcavationOrder")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/excavation-orders")
def list_excavations():
    authenticate(ALL_ROLES)
    recs = list(db.excavations.values())
    fault_id = request.args.get("fault_record_id")
    if fault_id is not None:
        recs = [e for e in recs if e["fault_record_id"] == fault_id]
    status = request.args.get("status")
    if status is not None:
        recs = [e for e in recs if e["status"] == status]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/excavation-orders/<eid>/repair-splices")
def excavation_splices(eid):
    authenticate(ALL_ROLES)
    get_or_404(db.excavations, eid, "ExcavationOrder")
    recs = [s for s in db.splices.values() if s["excavation_order_id"] == eid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/excavation-orders/<eid>/permit")
def permit_excavation(eid):
    authenticate(["FaultCrewLead"])
    rec = get_or_404(db.excavations, eid, "ExcavationOrder")
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT excavation can be permitted")
    rec["status"] = "PERMITTED"
    workflow.touch(rec)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/excavation-orders/<eid>/start")
def start_excavation(eid):
    authenticate(["FaultCrewLead"])
    rec = get_or_404(db.excavations, eid, "ExcavationOrder")
    if rec["status"] != "PERMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PERMITTED excavation can be started")
    now = db.now()
    if not (rec["dig_start"] <= now < rec["dig_end"]):
        raise ApiError(ERR_WINDOW_NOT_ACTIVE, 409, "Logical clock is outside the dig interval")
    fault = db.faults[rec["fault_record_id"]]
    job = db.jobs[fault["test_job_id"]]
    window = db.windows[job["outage_window_id"]]
    if window["status"] != "ACTIVE":
        raise ApiError(ERR_WINDOW_NOT_ACTIVE, 409, "The job's outage window is not ACTIVE")
    rec["status"] = "IN_PROGRESS"
    workflow.touch(rec)
    if fault["status"] == "PINPOINTED":
        fault["status"] = "EXCAVATING"
        workflow.touch(fault)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/excavation-orders/<eid>/backfill")
def backfill_excavation(eid):
    authenticate(["FaultCrewLead"])
    rec = get_or_404(db.excavations, eid, "ExcavationOrder")
    if rec["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an IN_PROGRESS excavation can be backfilled")
    curing = any(
        s["excavation_order_id"] == eid and s["status"] in ("CURING", "COMPLETED")
        for s in db.splices.values()
    )
    if not curing:
        raise ApiError(ERR_SPLICE_NOT_CURING, 409, "No splice referencing this excavation is CURING or COMPLETED")
    rec["status"] = "BACKFILLED"
    workflow.touch(rec)
    return success(serialize(rec))


@bp.post("/cable-diagnostics/excavation-orders/<eid>/cancel")
def cancel_excavation(eid):
    authenticate(["FaultCrewLead"])
    rec = get_or_404(db.excavations, eid, "ExcavationOrder")
    if rec["status"] not in ("DRAFT", "PERMITTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT or PERMITTED excavation can be cancelled")
    rec["status"] = "CANCELLED"
    workflow.touch(rec)
    fault = db.faults[rec["fault_record_id"]]
    job = db.jobs[fault["test_job_id"]]
    job["committed_cost_cents"] -= rec["cost_cents"]
    workflow.touch(job)
    return success(serialize(rec))
