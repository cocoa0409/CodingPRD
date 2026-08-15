"""LockoutWindow endpoints (feeder-pooled 30-minute clearance buffer)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_INVALID_STATE, ERR_INVALID_WINDOW,
                    ERR_LOCKOUT_CONFLICT, ERR_SAFETY_PLAN_NOT_ACTIVE)
from helpers import lockout_or_404, project_or_404, sorted_items, touch
from middleware import ROLES, require_roles
from response import success, success_list
from serialize import lockout_json
from util import new_id, now_iso
from validators import get_body, pagination, req_datetime, req_str

bp = Blueprint("lockout_windows", __name__)

LOCKOUT_BUFFER_MIN = 30


@bp.post("/v1/lockout-windows")
@require_roles("SafetyOfficer")
def create_lockout():
    body = get_body()
    pid = body.get("project_id")
    if isinstance(pid, str):
        project_or_404(pid)
    # schema (priority 7)
    pid = req_str(body, "project_id")
    feeder_id = req_str(body, "feeder_id")
    starts_dt = req_datetime(body, "starts_at")
    ends_dt = req_datetime(body, "ends_at")
    # priority 9: project must have an ACTIVE safety plan
    if not any(sp["project_id"] == pid and sp["status"] == "ACTIVE"
               for sp in db.safety_plans.values()):
        raise ApiError(ERR_SAFETY_PLAN_NOT_ACTIVE, 409,
                       "no ACTIVE safety plan for the project")
    # priority 22: window well-formedness
    if not ends_dt > starts_dt:
        raise ApiError(ERR_INVALID_WINDOW, 422, "ends_at must be strictly after starts_at")
    # priority 23: 30-minute clearance vs SCHEDULED/ACTIVE windows on same project+feeder
    buffer = timedelta(minutes=LOCKOUT_BUFFER_MIN)
    for w in db.lockout_windows.values():
        if w["project_id"] != pid or w["feeder_id"] != feeder_id:
            continue
        if w["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if starts_dt >= w["_ends_dt"] + buffer or ends_dt + buffer <= w["_starts_dt"]:
            continue
        raise ApiError(ERR_LOCKOUT_CONFLICT, 409,
                       "window violates the 30-minute clearance buffer on this feeder")
    ts = now_iso()
    w = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "project_id": pid,
        "feeder_id": feeder_id,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "status": "SCHEDULED",
        "_starts_dt": starts_dt,
        "_ends_dt": ends_dt,
        "_seq": db.next_seq(),
    }
    db.lockout_windows[w["id"]] = w
    return success(lockout_json(w), 201)


@bp.get("/v1/projects/<pid>/lockout-windows")
@require_roles(*ROLES)
def list_lockouts(pid):
    project_or_404(pid)
    limit, offset = pagination()
    feeder = request.args.get("feeder_id")
    items = [w for w in db.lockout_windows.values() if w["project_id"] == pid]
    if feeder is not None:
        items = [w for w in items if w["feeder_id"] == feeder]
    items = sorted_items(items)
    total = len(items)
    return success_list([lockout_json(w) for w in items[offset:offset + limit]],
                        limit, offset, total)


@bp.post("/v1/lockout-windows/<wid>/cancel")
@require_roles("SafetyOfficer")
def cancel_lockout(wid):
    w = lockout_or_404(wid)
    if w["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "only a SCHEDULED lockout can be cancelled")
    w["status"] = "CANCELLED"
    touch(w)
    return success(lockout_json(w))


@bp.post("/v1/lockout-windows/<wid>/release")
@require_roles("SafetyOfficer")
def release_lockout(wid):
    w = lockout_or_404(wid)
    if w["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "only an ACTIVE lockout can be released")
    w["status"] = "RELEASED"
    touch(w)
    return success(lockout_json(w))
