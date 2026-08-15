import uuid

from flask import Blueprint, request

import db
import util
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_WINDOW_IN_PAST,
    ERR_WINDOW_OVERLAP, ERR_WINDOW_NOT_ACTIVE,
)
from helpers import (
    body_dict, req_str, req_enum, req_dt, get_or_404, serialize, serialize_list,
    paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import calc
from services import workflow

bp = Blueprint("windows", __name__)

OPEN_WINDOW_STATES = ("REQUESTED", "APPROVED", "ACTIVE")


def _other_open_window_exists(circuit_id, exclude_id):
    return any(
        w["id"] != exclude_id
        and w["circuit_id"] == circuit_id
        and w["status"] in ("APPROVED", "ACTIVE")
        for w in db.windows.values()
    )


@bp.post("/cable-diagnostics/outage-windows")
def create_window():
    authenticate(["NetworkPlanner"])
    body = body_dict()
    circuit_id = req_str(body, "circuit_id")
    kind = req_enum(body, "kind", calc.WINDOW_KINDS)
    window_start = req_dt(body, "window_start")
    window_end = req_dt(body, "window_end")
    if window_end <= window_start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "window_end must be strictly after window_start")
    get_or_404(db.circuits, circuit_id, "CableCircuit")
    now = db.now()
    if window_start < now:
        raise ApiError(ERR_WINDOW_IN_PAST, 409, "window_start precedes the logical clock")
    for w in db.windows.values():
        if w["circuit_id"] == circuit_id and w["status"] in OPEN_WINDOW_STATES:
            if window_start < w["window_end"] and w["window_start"] < window_end:
                raise ApiError(ERR_WINDOW_OVERLAP, 409, "window overlaps an existing open window")
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "circuit_id": circuit_id,
        "kind": kind,
        "window_start": window_start,
        "window_end": window_end,
        "status": "REQUESTED",
        "duration_minutes": util.whole_minutes(window_start, window_end),
        "restored_at": None,
        "overrun_minutes": 0,
        "overrun_charge_cents": 0,
        "estimated_charge_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.windows[rec["id"]] = rec
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/outage-windows/<wid>")
def get_window(wid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.windows, wid, "OutageWindow")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/outage-windows")
def list_windows():
    authenticate(ALL_ROLES)
    recs = list(db.windows.values())
    circuit_id = request.args.get("circuit_id")
    if circuit_id is not None:
        recs = [w for w in recs if w["circuit_id"] == circuit_id]
    status = request.args.get("status")
    if status is not None:
        recs = [w for w in recs if w["status"] == status]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/outage-windows/<wid>/test-jobs")
def window_jobs(wid):
    authenticate(ALL_ROLES)
    get_or_404(db.windows, wid, "OutageWindow")
    recs = [j for j in db.jobs.values() if j["outage_window_id"] == wid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.post("/cable-diagnostics/outage-windows/<wid>/approve")
def approve_window(wid):
    authenticate(["NetworkPlanner"])
    w = get_or_404(db.windows, wid, "OutageWindow")
    if w["status"] != "REQUESTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Window is not REQUESTED")
    circuit = db.circuits[w["circuit_id"]]
    if circuit["status"] not in ("IN_SERVICE", "OUTAGE_PENDING"):
        raise ApiError(ERR_INVALID_STATE, 409, "Circuit does not accept window approval in %s" % circuit["status"])
    circuit["approved_outage_minutes_total"] += w["duration_minutes"]
    w["estimated_charge_cents"] = calc.estimated_charge_cents(w["duration_minutes"], w["kind"])
    if circuit["status"] == "IN_SERVICE":
        circuit["status"] = "OUTAGE_PENDING"
    w["status"] = "APPROVED"
    workflow.touch(w)
    workflow.touch(circuit)
    return success(serialize(w))


@bp.post("/cable-diagnostics/outage-windows/<wid>/activate")
def activate_window(wid):
    authenticate(["NetworkPlanner"])
    w = get_or_404(db.windows, wid, "OutageWindow")
    if w["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Window is not APPROVED")
    now = db.now()
    if not (w["window_start"] <= now < w["window_end"]):
        raise ApiError(ERR_WINDOW_NOT_ACTIVE, 409, "Logical clock is outside the window bounds")
    w["status"] = "ACTIVE"
    workflow.touch(w)
    return success(serialize(w))


@bp.post("/cable-diagnostics/outage-windows/<wid>/close")
def close_window(wid):
    authenticate(["NetworkPlanner"])
    body = body_dict()
    restored_at = req_dt(body, "restored_at")
    w = get_or_404(db.windows, wid, "OutageWindow")
    if w["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Window is not ACTIVE")
    if restored_at < w["window_start"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "restored_at precedes window_start")

    w["status"] = "CLOSED"
    w["restored_at"] = restored_at
    overrun = util.ceil_minutes(restored_at - w["window_end"]) if restored_at > w["window_end"] else 0
    w["overrun_minutes"] = overrun
    w["overrun_charge_cents"] = calc.overrun_charge_cents(overrun, w["kind"])
    workflow.touch(w)

    circuit = db.circuits[w["circuit_id"]]
    circuit["approved_outage_minutes_total"] -= w["duration_minutes"]
    # cascade hop 1: circuit restoration
    if circuit["status"] == "RESTORING":
        circuit["status"] = "IN_SERVICE"
    elif circuit["status"] == "OUTAGE_PENDING" and not _other_open_window_exists(circuit["id"], w["id"]):
        circuit["status"] = "IN_SERVICE"
    workflow.touch(circuit)

    # cascade hops 2 and 3: release open assignments of this circuit's jobs
    circuit_job_ids = {j["id"] for j in db.jobs.values() if j["circuit_id"] == circuit["id"]}
    for a in list(db.assignments.values()):
        if a["test_job_id"] in circuit_job_ids and a["status"] in ("CONFIRMED", "ACTIVE"):
            workflow.release_assignment(a)
    return success(serialize(w))


@bp.post("/cable-diagnostics/outage-windows/<wid>/cancel")
def cancel_window(wid):
    authenticate(["NetworkPlanner"])
    w = get_or_404(db.windows, wid, "OutageWindow")
    if w["status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only REQUESTED or APPROVED windows can be cancelled")
    if w["status"] == "APPROVED":
        for j in db.jobs.values():
            if j["outage_window_id"] == w["id"] and j["status"] not in workflow.TERMINAL_JOB_STATES:
                raise ApiError(ERR_INVALID_STATE, 409, "A non-terminal test job references this window")
        circuit = db.circuits[w["circuit_id"]]
        circuit["approved_outage_minutes_total"] -= w["duration_minutes"]
        if circuit["status"] == "OUTAGE_PENDING" and not _other_open_window_exists(circuit["id"], w["id"]):
            circuit["status"] = "IN_SERVICE"
        workflow.touch(circuit)
    w["status"] = "CANCELLED"
    workflow.touch(w)
    return success(serialize(w))
