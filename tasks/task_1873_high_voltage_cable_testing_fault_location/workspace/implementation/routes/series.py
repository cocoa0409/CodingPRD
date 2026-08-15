import uuid
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_GROUNDING_NOT_VERIFIED,
    ERR_NO_EQUIPMENT_ON_SITE, ERR_METHOD_NOT_REQUESTED, ERR_VOLTAGE_MISMATCH,
    ERR_NO_READINGS, ERR_STEP_INCOMPLETE, ERR_STEP_OUT_OF_RANGE,
    ERR_DUPLICATE_STEP,
)
from helpers import (
    body_dict, req_str, req_num, opt_bool, get_or_404, serialize,
    serialize_list, paginate, is_int,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import calc
from services import workflow
from util import dec as dec_num

bp = Blueprint("series", __name__)


@bp.post("/cable-diagnostics/test-series")
def create_series():
    authenticate(["TestSupervisor"])
    body = body_dict()
    test_job_id = req_str(body, "test_job_id")
    method = req_str(body, "method")
    if method not in calc.TEST_METHODS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Unknown test method")
    test_voltage_kv = req_num(body, "test_voltage_kv")
    is_retest = opt_bool(body, "is_retest", False)
    retest_of_fault_id = body.get("retest_of_fault_id")
    if is_retest:
        if retest_of_fault_id is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "retest_of_fault_id is required when is_retest is true")
    elif retest_of_fault_id is not None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "retest_of_fault_id is forbidden when is_retest is false")

    job = get_or_404(db.jobs, test_job_id, "TestJob")
    fault = None
    if retest_of_fault_id is not None:
        fault = get_or_404(db.faults, retest_of_fault_id, "FaultRecord")

    if job["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Job must be IN_PROGRESS")
    if is_retest and fault["status"] != "REPAIRED":
        raise ApiError(ERR_INVALID_STATE, 409, "Linked fault must be REPAIRED for a re-test series")

    if method not in job["requested_methods"]:
        raise ApiError(ERR_METHOD_NOT_REQUESTED, 409, "Method not among the job's requested_methods")
    if method in calc.VLF_METHODS:
        circuit = db.circuits[job["circuit_id"]]
        target = Decimal("1.5") * calc.U0_KV[circuit["voltage_class"]]
        v = dec_num(test_voltage_kv)
        tolerance = target * Decimal("0.05")
        if v < target - tolerance or v > target + tolerance:
            raise ApiError(ERR_VOLTAGE_MISMATCH, 422, "test_voltage_kv outside +/-5% of 1.5 x U0")

    now = db.now()
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "test_job_id": test_job_id,
        "method": method,
        "test_voltage_kv": test_voltage_kv,
        "is_retest": is_retest,
        "retest_of_fault_id": retest_of_fault_id if is_retest else None,
        "step_count": 3 if method in calc.VLF_METHODS else 1,
        "status": "SETUP",
        "verdict_as_tested": None,
        "verdict_temperature_corrected": None,
        "verdict": None,
        "max_tan_delta_e3": None,
        "max_pd_pc": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.series[rec["id"]] = rec
    if is_retest and fault is not None:
        fault["status"] = "RETESTING"
        workflow.touch(fault)
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/test-series/<sid>")
def get_series(sid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.series, sid, "TestSeries")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/test-series")
def list_series():
    authenticate(ALL_ROLES)
    recs = list(db.series.values())
    job_id = request.args.get("test_job_id")
    if job_id is not None:
        recs = [s for s in recs if s["test_job_id"] == job_id]
    status = request.args.get("status")
    if status is not None:
        recs = [s for s in recs if s["status"] == status]
    method = request.args.get("method")
    if method is not None:
        recs = [s for s in recs if s["method"] == method]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/test-series/<sid>/energize")
def energize_series(sid):
    authenticate(["TestSupervisor"])
    series = get_or_404(db.series, sid, "TestSeries")
    if series["status"] != "SETUP":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SETUP series can be energized")
    job = db.jobs[series["test_job_id"]]
    if job["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Job must be IN_PROGRESS")
    grounded = any(
        p["test_job_id"] == job["id"] and p["status"] == "GROUNDING_VERIFIED"
        for p in db.permits.values()
    )
    if not grounded:
        raise ApiError(ERR_GROUNDING_NOT_VERIFIED, 409, "The job's isolation permit is not GROUNDING_VERIFIED")
    now = db.now()
    on_site = any(
        a["test_job_id"] == job["id"]
        and a["status"] in ("CONFIRMED", "ACTIVE")
        and a["mobilize_at"] <= now <= a["demobilize_at"]
        for a in db.assignments.values()
    )
    if not on_site:
        raise ApiError(ERR_NO_EQUIPMENT_ON_SITE, 409, "No qualifying equipment assignment is on site")
    series["status"] = "ENERGIZING"
    workflow.touch(series)
    circuit = db.circuits[job["circuit_id"]]
    if circuit["status"] == "GROUNDED":
        circuit["status"] = "UNDER_TEST"
        workflow.touch(circuit)
    return success(serialize(series))


@bp.post("/cable-diagnostics/test-series/<sid>/readings")
def append_reading(sid):
    user_id, _ = authenticate(["FieldTechnician"])
    body = body_dict()
    if "step_index" not in body or body["step_index"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: step_index")
    step_index = body["step_index"]
    if not is_int(step_index) or step_index < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "step_index must be a non-negative integer")
    applied_voltage_kv = req_num(body, "applied_voltage_kv")
    if applied_voltage_kv <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "applied_voltage_kv must be > 0")
    ambient_temp_c = req_num(body, "ambient_temp_c")

    series = get_or_404(db.series, sid, "TestSeries")

    tan_delta_e3 = body.get("tan_delta_e3")
    pd_level_pc = body.get("pd_level_pc")
    pd_location_m = body.get("pd_location_m")
    method = series["method"]
    if method in calc.VLF_METHODS:
        if tan_delta_e3 is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "tan_delta_e3 is required for VLF methods")
    elif tan_delta_e3 is not None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "tan_delta_e3 is forbidden for PD_MAPPING")
    if method in ("VLF_WITH_PD", "PD_MAPPING"):
        if pd_level_pc is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "pd_level_pc is required for this method")
    elif pd_level_pc is not None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "pd_level_pc is forbidden for VLF_TAN_DELTA")
    if tan_delta_e3 is not None and not is_num_reading(tan_delta_e3):
        raise ApiError(ERR_INVALID_REQUEST, 400, "tan_delta_e3 must be a number")
    if pd_level_pc is not None and not is_num_reading(pd_level_pc):
        raise ApiError(ERR_INVALID_REQUEST, 400, "pd_level_pc must be a number")
    if pd_location_m is not None and not is_num_reading(pd_location_m):
        raise ApiError(ERR_INVALID_REQUEST, 400, "pd_location_m must be a number")

    if series["status"] not in ("ENERGIZING", "LOGGING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Readings may be appended only while ENERGIZING or LOGGING")
    if step_index >= series["step_count"]:
        raise ApiError(ERR_STEP_OUT_OF_RANGE, 422, "step_index must be below step_count")
    for r in db.readings.values():
        if r["test_series_id"] == sid and r["step_index"] == step_index:
            raise ApiError(ERR_DUPLICATE_STEP, 409, "A reading already exists for this step")

    now = db.now()
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "test_series_id": sid,
        "step_index": step_index,
        "applied_voltage_kv": applied_voltage_kv,
        "tan_delta_e3": tan_delta_e3,
        "pd_level_pc": pd_level_pc,
        "pd_location_m": pd_location_m,
        "ambient_temp_c": ambient_temp_c,
        "recorded_by_user_id": user_id,
        "created_at": now,
    }
    db.readings[rec["id"]] = rec
    if series["status"] == "ENERGIZING":
        series["status"] = "LOGGING"
        workflow.touch(series)
    return success(serialize(rec), code=201)


def is_num_reading(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@bp.get("/cable-diagnostics/test-series/<sid>/readings")
def list_readings(sid):
    authenticate(ALL_ROLES)
    get_or_404(db.series, sid, "TestSeries")
    recs = [r for r in db.readings.values() if r["test_series_id"] == sid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/test-series/<sid>/faults")
def series_faults(sid):
    authenticate(ALL_ROLES)
    get_or_404(db.series, sid, "TestSeries")
    recs = [f for f in db.faults.values() if f["test_series_id"] == sid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/test-series/<sid>/evaluate")
def evaluate_series(sid):
    authenticate(["TestSupervisor"])
    series = get_or_404(db.series, sid, "TestSeries")
    if series["status"] not in ("ENERGIZING", "LOGGING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ENERGIZING or LOGGING series can be evaluated")
    readings = [r for r in db.readings.values() if r["test_series_id"] == sid]
    if not readings:
        raise ApiError(ERR_NO_READINGS, 409, "At least one reading is required")
    have_steps = {r["step_index"] for r in readings}
    if any(i not in have_steps for i in range(series["step_count"])):
        raise ApiError(ERR_STEP_INCOMPLETE, 409, "Every step 0..step_count-1 requires a reading")

    job = db.jobs[series["test_job_id"]]
    as_tested, corrected, official, max_td, max_pd = calc.compute_verdicts(
        series["method"], readings, job["use_temperature_correction"]
    )
    series["verdict_as_tested"] = as_tested
    series["verdict_temperature_corrected"] = corrected
    series["verdict"] = official
    series["max_tan_delta_e3"] = max_td
    series["max_pd_pc"] = max_pd
    series["status"] = "EVALUATED"
    workflow.touch(series)

    if official == "FAIL":
        _create_fault(series)
    return success(serialize(series))


def _create_fault(series):
    now = db.now()
    fault = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "test_job_id": series["test_job_id"],
        "test_series_id": series["id"],
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
    circuit = db.circuits[job["circuit_id"]]
    workflow.fault_opened(circuit)
    return fault


@bp.post("/cable-diagnostics/test-series/<sid>/accept")
def accept_series(sid):
    authenticate(["NetworkPlanner"])
    series = get_or_404(db.series, sid, "TestSeries")
    if series["status"] != "EVALUATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an EVALUATED series can be accepted")
    series["status"] = "ACCEPTED"
    workflow.touch(series)
    workflow.maybe_auto_evaluate(db.jobs[series["test_job_id"]])
    return success(serialize(series))


@bp.post("/cable-diagnostics/test-series/<sid>/invalidate")
def invalidate_series(sid):
    authenticate(["TestSupervisor"])
    body = body_dict()
    req_str(body, "reason")
    series = get_or_404(db.series, sid, "TestSeries")
    if series["status"] != "EVALUATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an EVALUATED series can be invalidated")
    series["status"] = "INVALID"
    workflow.touch(series)
    if series["is_retest"] and series["retest_of_fault_id"]:
        fault = db.faults.get(series["retest_of_fault_id"])
        if fault and fault["status"] == "RETESTING":
            fault["status"] = "REPAIRED"
            workflow.touch(fault)
    workflow.maybe_auto_evaluate(db.jobs[series["test_job_id"]])
    return success(serialize(series))
