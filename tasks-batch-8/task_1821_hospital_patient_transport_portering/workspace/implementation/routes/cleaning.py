"""Cleaning task routes: advance pipeline (start / finish / verify / rework)
and reads."""

from flask import Blueprint, request

from db import store, now
from errors import ApiError
from middleware import require_roles, forbidden
from response import ok, ok_list, public, public_list, sort_created, paginate
from services import DWELL_SECONDS_DEEP, touch, auto_dispatch_eval
from util import get_body, req_enum, opt_string, parse_datetime, fmt

bp = Blueprint("cleaning", __name__)


def _not_found(what):
    raise ApiError("ERR_NOT_FOUND", 404, "{} not found".format(what))


@bp.post("/transport/cleaning-tasks/<task_id>/advance")
def advance_cleaning_task(task_id):
    uid, role = require_roles("HousekeepingStaff", "TransportSupervisor")
    data = get_body()
    to_state = req_enum(data, "to_state", {"IN_PROGRESS", "AWAITING_VERIFICATION", "VERIFIED"})
    opt_string(data, "note")  # accepted, not persisted

    task = store.cleaning_tasks.get(task_id)
    if task is None:
        _not_found("cleaning task")
    asset = store.equipment_assets.get(task["equipment_asset_id"])

    # Role-payload restrictions (tier 2): HousekeepingStaff performs,
    # TransportSupervisor verifies and reworks.
    if to_state == "VERIFIED" and role != "TransportSupervisor":
        forbidden("verification is supervisor-only")
    if to_state == "AWAITING_VERIFICATION" and role != "HousekeepingStaff":
        forbidden("finishing a cleaning task is housekeeping-only")

    cur = task["status"]
    if to_state == "IN_PROGRESS":
        if cur == "PENDING":
            if role != "HousekeepingStaff":
                forbidden("starting a cleaning task is housekeeping-only")
            if asset is None or asset["status"] != "AWAITING_CLEANING":
                raise ApiError("ERR_INVALID_ASSET_STATE", 409,
                               "asset is not AWAITING_CLEANING")
            task["started_at"] = fmt(now())
            task["status"] = "IN_PROGRESS"
            asset["status"] = "IN_CLEANING"
            touch(asset)
            touch(task)
        elif cur == "AWAITING_VERIFICATION":
            if role != "TransportSupervisor":
                forbidden("rework is supervisor-only")
            task["rework_count"] += 1
            task["started_at"] = fmt(now())
            task["status"] = "IN_PROGRESS"
            touch(task)
        else:
            raise ApiError("ERR_INVALID_CLEANING_STATE", 409,
                           "cannot advance from {} to IN_PROGRESS".format(cur))

    elif to_state == "AWAITING_VERIFICATION":
        if cur != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_CLEANING_STATE", 409,
                           "cannot advance from {} to AWAITING_VERIFICATION".format(cur))
        if task["task_type"] == "DEEP":
            started = parse_datetime(task["started_at"], "started_at")
            if (now() - started).total_seconds() < DWELL_SECONDS_DEEP:
                raise ApiError("ERR_DWELL_NOT_ELAPSED", 422,
                               "DEEP cleaning requires a 15-minute dwell before finishing")
        task["finished_at"] = fmt(now())
        task["performed_by"] = uid
        task["status"] = "AWAITING_VERIFICATION"
        touch(task)

    else:  # VERIFIED
        if cur != "AWAITING_VERIFICATION":
            raise ApiError("ERR_INVALID_CLEANING_STATE", 409,
                           "cannot advance from {} to VERIFIED".format(cur))
        if uid == task["performed_by"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTY", 403,
                           "verifier must differ from the cleaning performer")
        task["verified_at"] = fmt(now())
        task["verified_by"] = uid
        task["status"] = "VERIFIED"
        touch(task)
        if asset is not None:
            asset["status"] = "AVAILABLE"
            asset["isolation_contaminated"] = False
            touch(asset)
            auto_dispatch_eval(asset)

    return ok(public(task))


@bp.get("/transport/cleaning-tasks")
def list_cleaning_tasks():
    require_roles("HousekeepingStaff", "TransportDispatcher", "TransportSupervisor")
    recs = sort_created(store.cleaning_tasks.values())
    for param in ("status", "equipment_asset_id", "transport_request_id"):
        v = request.args.get(param)
        if v is not None:
            recs = [t for t in recs if str(t.get(param)) == v]
    page, meta = paginate(recs)
    return ok_list(public_list(page), meta)


@bp.get("/transport/cleaning-tasks/<task_id>")
def get_cleaning_task(task_id):
    require_roles("HousekeepingStaff", "TransportDispatcher", "TransportSupervisor")
    task = store.cleaning_tasks.get(task_id)
    if task is None:
        _not_found("cleaning task")
    return ok(public(task))
