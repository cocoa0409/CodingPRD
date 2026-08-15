import uuid

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_WINDOW_NOT_ACTIVE, ERR_PERMIT_NOT_RELEASED, ERR_SPLICE_EXISTS,
    ERR_CIRCUIT_BUSY, ERR_CROSS_REFERENCE_MISMATCH, ERR_BUDGET_EXCEEDED,
)
from helpers import (
    body_dict, req_str, req_int, req_field, opt_bool, get_or_404, serialize,
    serialize_list, paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import calc
from services import workflow

bp = Blueprint("jobs", __name__)


def _open_splice_on_circuit(circuit_id):
    """Any fault of this circuit with a splice still in an open state."""
    for f in workflow.faults_of_circuit(circuit_id):
        for s in db.splices.values():
            if s["fault_record_id"] == f["id"] and s["status"] in workflow.OPEN_SPLICE_STATES:
                return True
    return False


def _check_methods(body):
    methods = req_field(body, "requested_methods")
    if not isinstance(methods, list) or not methods:
        raise ApiError(ERR_INVALID_REQUEST, 400, "requested_methods must be a non-empty array")
    for m in methods:
        if m not in calc.TEST_METHODS:
            raise ApiError(ERR_INVALID_REQUEST, 400, "requested_methods contains an unknown method")
    return methods


@bp.post("/cable-diagnostics/test-jobs")
def create_job():
    authenticate(["NetworkPlanner"])
    body = body_dict()
    circuit_id = req_str(body, "circuit_id")
    outage_window_id = req_str(body, "outage_window_id")
    methods = _check_methods(body)
    budget = req_int(body, "approved_budget_cents")
    if budget <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "approved_budget_cents must be > 0")
    use_temp = opt_bool(body, "use_temperature_correction", False)

    get_or_404(db.circuits, circuit_id, "CableCircuit")
    window = get_or_404(db.windows, outage_window_id, "OutageWindow")

    if window["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Outage window is not APPROVED")
    if _open_splice_on_circuit(circuit_id):
        raise ApiError(ERR_SPLICE_EXISTS, 409, "An open splice exists on a fault of this circuit")
    for j in db.jobs.values():
        if j["circuit_id"] == circuit_id and j["status"] not in workflow.TERMINAL_JOB_STATES:
            raise ApiError(ERR_CIRCUIT_BUSY, 409, "A non-terminal test job exists for the circuit")
    if window["circuit_id"] != circuit_id:
        raise ApiError(ERR_CROSS_REFERENCE_MISMATCH, 422, "Window does not belong to the named circuit")

    now = db.now()
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "circuit_id": circuit_id,
        "outage_window_id": outage_window_id,
        "requested_methods": list(methods),
        "approved_budget_cents": budget,
        "use_temperature_correction": use_temp,
        "estimate_cents": None,
        "committed_cost_cents": 0,
        "status": "DRAFT",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.jobs[rec["id"]] = rec
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/test-jobs/<jid>")
def get_job(jid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.jobs, jid, "TestJob")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/test-jobs")
def list_jobs():
    authenticate(ALL_ROLES)
    recs = list(db.jobs.values())
    circuit_id = request.args.get("circuit_id")
    if circuit_id is not None:
        recs = [j for j in recs if j["circuit_id"] == circuit_id]
    window_id = request.args.get("outage_window_id")
    if window_id is not None:
        recs = [j for j in recs if j["outage_window_id"] == window_id]
    status = request.args.get("status")
    if status is not None:
        recs = [j for j in recs if j["status"] == status]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/test-jobs/<jid>/plan")
def plan_job(jid):
    authenticate(["NetworkPlanner"])
    job = get_or_404(db.jobs, jid, "TestJob")
    if job["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT job can be planned")
    circuit = db.circuits[job["circuit_id"]]
    estimate = calc.job_estimate_cents(circuit, job["requested_methods"])
    if estimate > job["approved_budget_cents"]:
        raise ApiError(ERR_BUDGET_EXCEEDED, 422, "Estimate exceeds the approved budget")
    job["estimate_cents"] = estimate
    job["status"] = "PLANNED"
    workflow.touch(job)
    return success(serialize(job))


@bp.post("/cable-diagnostics/test-jobs/<jid>/reschedule")
def reschedule_job(jid):
    authenticate(["NetworkPlanner"])
    body = body_dict()
    new_window_id = req_str(body, "outage_window_id")
    expected = req_int(body, "expected_test_job_version")

    job = get_or_404(db.jobs, jid, "TestJob")
    window = get_or_404(db.windows, new_window_id, "OutageWindow")

    if expected != job["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_test_job_version does not match the job version")
    if job["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PLANNED job can be rescheduled")
    if window["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Replacement window is not APPROVED")
    if _open_splice_on_circuit(job["circuit_id"]):
        raise ApiError(ERR_SPLICE_EXISTS, 409, "An open splice exists on a fault of this circuit")
    if window["circuit_id"] != job["circuit_id"]:
        raise ApiError(ERR_CROSS_REFERENCE_MISMATCH, 422, "Window does not belong to the job's circuit")

    job["outage_window_id"] = new_window_id
    workflow.touch(job)
    return success(serialize(job))


@bp.post("/cable-diagnostics/test-jobs/<jid>/start")
def start_job(jid):
    authenticate(["TestSupervisor"])
    job = get_or_404(db.jobs, jid, "TestJob")
    if job["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a PLANNED job can be started")
    window = db.windows[job["outage_window_id"]]
    if window["status"] != "ACTIVE":
        raise ApiError(ERR_WINDOW_NOT_ACTIVE, 409, "Outage window is not ACTIVE")
    job["status"] = "IN_PROGRESS"
    workflow.touch(job)
    return success(serialize(job))


@bp.post("/cable-diagnostics/test-jobs/<jid>/suspend")
def suspend_job(jid):
    authenticate(["TestSupervisor"])
    job = get_or_404(db.jobs, jid, "TestJob")
    if job["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an IN_PROGRESS job can be suspended")
    job["status"] = "SUSPENDED"
    workflow.touch(job)
    return success(serialize(job))


@bp.post("/cable-diagnostics/test-jobs/<jid>/resume")
def resume_job(jid):
    authenticate(["TestSupervisor"])
    job = get_or_404(db.jobs, jid, "TestJob")
    if job["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SUSPENDED job can be resumed")
    window = db.windows[job["outage_window_id"]]
    if window["status"] != "ACTIVE":
        raise ApiError(ERR_WINDOW_NOT_ACTIVE, 409, "Outage window is not ACTIVE")
    job["status"] = "IN_PROGRESS"
    workflow.touch(job)
    workflow.maybe_auto_evaluate(job)
    return success(serialize(job))


@bp.post("/cable-diagnostics/test-jobs/<jid>/complete")
def complete_job(jid):
    authenticate(["TestSupervisor"])
    job = get_or_404(db.jobs, jid, "TestJob")
    if job["status"] != "EVALUATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an EVALUATION job can be completed")
    released = any(
        p["test_job_id"] == jid and p["status"] == "RELEASED"
        for p in db.permits.values()
    )
    if not released:
        raise ApiError(ERR_PERMIT_NOT_RELEASED, 409, "The job's isolation permit is not RELEASED")
    job["status"] = "COMPLETED"
    workflow.touch(job)
    return success(serialize(job))


@bp.post("/cable-diagnostics/test-jobs/<jid>/abort")
def abort_job(jid):
    authenticate(["NetworkPlanner", "TestSupervisor"])
    job = get_or_404(db.jobs, jid, "TestJob")
    if job["status"] not in ("DRAFT", "PLANNED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT or PLANNED job can be aborted")
    job["status"] = "ABORTED"
    workflow.touch(job)
    for a in list(db.assignments.values()):
        if a["test_job_id"] == jid and a["status"] in ("RESERVED", "CONFIRMED"):
            workflow.cancel_assignment(a)
    return success(serialize(job))


@bp.get("/cable-diagnostics/test-jobs/<jid>/invoice")
def job_invoice(jid):
    authenticate(["NetworkPlanner", "AssetEngineer"])
    job = get_or_404(db.jobs, jid, "TestJob")
    return success(calc.job_invoice(job))


@bp.get("/cable-diagnostics/test-jobs/<jid>/isolation-permits")
def job_permits(jid):
    authenticate(ALL_ROLES)
    get_or_404(db.jobs, jid, "TestJob")
    recs = [p for p in db.permits.values() if p["test_job_id"] == jid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/test-jobs/<jid>/test-series")
def job_series(jid):
    authenticate(ALL_ROLES)
    get_or_404(db.jobs, jid, "TestJob")
    recs = [s for s in db.series.values() if s["test_job_id"] == jid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/test-jobs/<jid>/faults")
def job_faults(jid):
    authenticate(ALL_ROLES)
    get_or_404(db.jobs, jid, "TestJob")
    recs = [f for f in db.faults.values() if f["test_job_id"] == jid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/test-jobs/<jid>/equipment-assignments")
def job_assignments(jid):
    authenticate(ALL_ROLES)
    get_or_404(db.jobs, jid, "TestJob")
    recs = [a for a in db.assignments.values() if a["test_job_id"] == jid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)
