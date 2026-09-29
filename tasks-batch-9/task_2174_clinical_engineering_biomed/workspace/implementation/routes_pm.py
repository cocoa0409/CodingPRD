"""Preventive-maintenance tasks (PRD 3.3)."""
from __future__ import annotations

from flask import Blueprint

import services
import util
import validate as v
from auth import authenticate, current_user
from common import respond, respond_list
from errors import ApiError, bad_request
from store import store

bp = Blueprint("pm", __name__)

PM_STATUSES = ("SCHEDULED", "DEFERRED", "COMPLETED", "MISSED")
PM_RESULTS = ("PASS", "FAIL", "PASS_WITH_DEFECT")


@bp.post("/pm-tasks")
def create_pm_task():
    authenticate(["CEManager", "BiomedTech"])
    payload = v.body(required=("device_id", "window_start", "window_end"))
    device_id = v.req_id(payload, "device_id")
    window_start, start_dt = v.req_dt(payload, "window_start")
    window_end, end_dt = v.req_dt(payload, "window_end")
    if not end_dt > start_dt:
        raise bad_request("window_end must be strictly after window_start.")
    device = store.require("Device", device_id)
    if device["operational_state"] == "RETIRED":
        raise ApiError("ERR_DEVICE_RETIRED", "A retired unit may not be scheduled for PM.")
    record = store.new_record("PMTask", {
        "device_id": device_id,
        "window_start": window_start,
        "window_end": window_end,
        "due_at": window_end,
        "original_due_at": window_end,
        "status": "SCHEDULED",
        "deferral_count": 0,
        "result": None,
        "labor_minutes": 0,
        "completed_at": None,
        "completed_by_user_id": None,
        "on_time": False,
    })
    return respond(record, 201)


@bp.get("/pm-tasks/<tid>")
def read_pm_task(tid):
    authenticate(["CEManager", "BiomedTech"])
    return respond(store.require("PMTask", tid))


@bp.get("/pm-tasks")
def list_pm_tasks():
    authenticate(["CEManager", "BiomedTech"])
    limit, offset = v.pagination()
    device_id = v.query_str("device_id")
    status = v.query_enum("status", PM_STATUSES)
    records = store.ordered([
        t for t in store.all("PMTask")
        if (device_id is None or t["device_id"] == device_id)
        and (status is None or t["status"] == status)
    ])
    return respond_list(records, limit, offset)


@bp.post("/pm-tasks/<tid>/complete")
def complete_pm_task(tid):
    authenticate(["BiomedTech"])
    task = store.require("PMTask", tid)
    payload = v.body(required=("result", "labor_minutes"))
    result = v.req_enum(payload, "result", PM_RESULTS)
    labor_minutes = v.req_int(payload, "labor_minutes", minimum=0)

    if task["status"] not in ("SCHEDULED", "DEFERRED"):
        raise ApiError("ERR_INVALID_PM_TASK_STATE",
                       "A %s PM task can no longer be completed." % task["status"])
    device = store.require("Device", task["device_id"])
    if device["operational_state"] == "RETIRED":
        raise ApiError("ERR_DEVICE_RETIRED", "A retired unit may not receive PM.")
    if device["security_state"] == "QUARANTINED":
        raise ApiError("ERR_DEVICE_QUARANTINED", "A quarantined unit may not receive PM.")
    now = store.now()
    if not (util.parse_dt(task["window_start"]) <= now <= util.parse_dt(task["window_end"])):
        raise ApiError("ERR_PM_OUTSIDE_WINDOW",
                       "The logical clock is outside the task's current PM window.")

    task["completed_at"] = store.now_iso()
    task["completed_by_user_id"] = current_user()
    task["result"] = result
    task["labor_minutes"] = labor_minutes
    task["status"] = "COMPLETED"
    task["on_time"] = util.parse_dt(task["completed_at"]) <= util.parse_dt(task["original_due_at"])
    store.touch(task)

    if result == "FAIL":
        device["operational_state"] = "DOWN"
        store.touch(device)
        services.new_work_order(
            device, "CLINICAL_IMPACT", "PM failure on %s" % device["serial_number"]
        )
    elif result == "PASS_WITH_DEFECT":
        device["condition_score"] = min(5, device["condition_score"] + 1)
        services.recompute_replacement_score(device)
        store.touch(device)
    return respond(task)


@bp.post("/pm-tasks/<tid>/defer")
def defer_pm_task(tid):
    authenticate(["CEManager"])
    task = store.require("PMTask", tid)
    payload = v.body(required=("new_window_start", "new_window_end", "reason"))
    new_start, start_dt = v.req_dt(payload, "new_window_start")
    new_end, end_dt = v.req_dt(payload, "new_window_end")
    v.req_str(payload, "reason")
    if not end_dt > start_dt:
        raise bad_request("new_window_end must be strictly after new_window_start.")

    if task["status"] not in ("SCHEDULED", "DEFERRED"):
        raise ApiError("ERR_INVALID_PM_TASK_STATE",
                       "A %s PM task can no longer be deferred." % task["status"])
    if task["deferral_count"] >= 2:
        raise ApiError("ERR_DEFERRAL_LIMIT_EXCEEDED",
                       "This PM task has already been deferred twice.")

    task["window_start"] = new_start
    task["window_end"] = new_end
    task["due_at"] = new_end
    task["deferral_count"] = task["deferral_count"] + 1
    task["status"] = "DEFERRED"
    store.touch(task)
    return respond(task)
