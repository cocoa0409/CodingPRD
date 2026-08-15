import uuid

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_VERDICT_NOT_FAIL,
    ERR_FAULT_ALREADY_RECORDED,
)
from helpers import (
    body_dict, req_str, req_num, opt_bool, get_or_404, serialize,
    serialize_list, paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import calc
from services import workflow
from util import dec as dec_num

bp = Blueprint("faults", __name__)


@bp.post("/cable-diagnostics/faults")
def create_fault():
    authenticate(["TestSupervisor"])
    body = body_dict()
    test_series_id = req_str(body, "test_series_id")
    series = get_or_404(db.series, test_series_id, "TestSeries")
    if series["verdict"] != "MONITOR":
        raise ApiError(ERR_VERDICT_NOT_FAIL, 409, "Manual fault creation requires a MONITOR verdict")
    for f in db.faults.values():
        if f["test_series_id"] == test_series_id:
            raise ApiError(ERR_FAULT_ALREADY_RECORDED, 409, "A fault already exists for this series")
    now = db.now()
    fault = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "test_job_id": series["test_job_id"],
        "test_series_id": test_series_id,
        "status": "SUSPECTED",
        "pinpoint_method": None,
        "trace_time_us": None,
        "velocity_factor_used": None,
        "pinpointed_distance_m": None,
        "alternate_distance_m": None,
        "corridor_start_m": None,
        "corridor_end_m": None,
        "closed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.faults[fault["id"]] = fault
    job = db.jobs[series["test_job_id"]]
    workflow.fault_opened(db.circuits[job["circuit_id"]])
    return success(serialize(fault), code=201)


@bp.get("/cable-diagnostics/faults/<fid>")
def get_fault(fid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.faults, fid, "FaultRecord")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/faults")
def list_faults():
    authenticate(ALL_ROLES)
    recs = list(db.faults.values())
    job_id = request.args.get("test_job_id")
    if job_id is not None:
        recs = [f for f in recs if f["test_job_id"] == job_id]
    series_id = request.args.get("test_series_id")
    if series_id is not None:
        recs = [f for f in recs if f["test_series_id"] == series_id]
    status = request.args.get("status")
    if status is not None:
        recs = [f for f in recs if f["status"] == status]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/faults/<fid>/pinpoint")
def pinpoint_fault(fid):
    authenticate(["FaultCrewLead"])
    body = body_dict()
    trace_time_us = req_num(body, "trace_time_us")
    t = dec_num(trace_time_us)
    if t is None or t <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "trace_time_us must be > 0")
    pinpoint_method = req_str(body, "pinpoint_method")
    if pinpoint_method not in calc.PINPOINT_METHODS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Unknown pinpoint_method")
    use_calibrated = opt_bool(body, "use_calibrated_velocity", False)

    fault = get_or_404(db.faults, fid, "FaultRecord")
    if fault["status"] not in ("SUSPECTED", "REOPENED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SUSPECTED or REOPENED fault can be pinpointed")

    circuit = workflow.circuit_of_fault(fault)
    computed = calc.pinpoint_distances(circuit, trace_time_us, use_calibrated)
    fault["pinpoint_method"] = pinpoint_method
    fault["trace_time_us"] = trace_time_us
    fault["velocity_factor_used"] = computed["velocity_factor_used"]
    fault["pinpointed_distance_m"] = computed["pinpointed_distance_m"]
    fault["alternate_distance_m"] = computed["alternate_distance_m"]
    fault["corridor_start_m"] = computed["corridor_start_m"]
    fault["corridor_end_m"] = computed["corridor_end_m"]
    fault["status"] = "PINPOINTED"
    workflow.touch(fault)
    return success(serialize(fault))


@bp.post("/cable-diagnostics/faults/<fid>/reopen")
def reopen_fault(fid):
    authenticate(["TestSupervisor"])
    fault = get_or_404(db.faults, fid, "FaultRecord")
    if fault["status"] != "CLOSED_VERIFIED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a CLOSED_VERIFIED fault can be reopened")
    workflow.fault_reopened(fault)
    return success(serialize(fault))


@bp.get("/cable-diagnostics/faults/<fid>/test-series")
def fault_series(fid):
    authenticate(ALL_ROLES)
    get_or_404(db.faults, fid, "FaultRecord")
    recs = [s for s in db.series.values() if s["retest_of_fault_id"] == fid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/faults/<fid>/excavation-orders")
def fault_excavations(fid):
    authenticate(ALL_ROLES)
    get_or_404(db.faults, fid, "FaultRecord")
    recs = [e for e in db.excavations.values() if e["fault_record_id"] == fid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/faults/<fid>/repair-splices")
def fault_splices(fid):
    authenticate(ALL_ROLES)
    get_or_404(db.faults, fid, "FaultRecord")
    recs = [s for s in db.splices.values() if s["fault_record_id"] == fid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)
