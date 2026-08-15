"""Shift and ShiftAssignment routes."""
from flask import Blueprint, request

from errors import err
from httpkit import (require_roles, body, req_str, req_enum, req_date,
                     paginate, sort_default, success)
from store import db, init_common, mark_dirty
from services import domain as dom
from services import serializers as ser
from routes.buses import ALL

bp = Blueprint("shifts", __name__)


def get_shift_or_404(shift_id):
    s = db["shifts"].get(shift_id)
    if s is None:
        raise err("ERR_NOT_FOUND", f"Shift {shift_id} not found")
    return s


def get_assignment_or_404(asg_id):
    a = db["assignments"].get(asg_id)
    if a is None:
        raise err("ERR_NOT_FOUND", f"ShiftAssignment {asg_id} not found")
    return a


@bp.post("/fleet/shifts")
def create_shift():
    require_roles("MaintenanceSupervisor")
    data = body()
    shift_date = req_date(data, "shift_date")
    shift_type = req_enum(data, "shift_type", dom.SHIFT_TYPES)
    required = data.get("required_headcount")
    if required is None:
        raise err("ERR_VALIDATION", "Missing required field: required_headcount")
    if not isinstance(required, dict):
        raise err("ERR_VALIDATION", "required_headcount must be an object")
    for k, v in required.items():
        if k not in dom.CERT_TYPES:
            raise err("ERR_VALIDATION",
                      f"required_headcount key {k} is not a known cert type")
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise err("ERR_VALIDATION",
                      "required_headcount values must be non-negative integers")
    shift = init_common({
        "shift_date": shift_date.isoformat(),
        "shift_type": shift_type,
        "required_headcount": dict(required),
        "status": "DRAFT",
    })
    db["shifts"][shift["id"]] = shift
    return success(ser.shift(shift), code=201)


@bp.get("/fleet/shifts/<sid>")
def get_shift(sid):
    require_roles(*ALL)
    return success(ser.shift(get_shift_or_404(sid)))


@bp.get("/fleet/shifts")
def list_shifts():
    require_roles(*ALL)
    items = list(db["shifts"].values())
    sd = request.args.get("shift_date")
    if sd is not None:
        items = [s for s in items if s["shift_date"] == sd]
    items = sort_default(items)
    page, meta_p = paginate(items)
    return success([ser.shift(s) for s in page], response_type="array",
                   pagination=meta_p)


@bp.post("/fleet/shifts/<sid>/publish")
def publish_shift(sid):
    require_roles("MaintenanceSupervisor")
    shift = get_shift_or_404(sid)
    if shift["status"] == "RECONCILED":
        raise err("ERR_ALREADY_TERMINAL", "Shift is RECONCILED")
    if shift["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE",
                  f"Cannot publish a shift in {shift['status']}")
    shift["status"] = "PUBLISHED"
    mark_dirty("shifts", shift["id"])
    return success(ser.shift(shift))


@bp.post("/fleet/shifts/<sid>/reconcile")
def reconcile_shift(sid):
    require_roles("MaintenanceSupervisor")
    shift = get_shift_or_404(sid)
    if shift["status"] == "RECONCILED":
        raise err("ERR_ALREADY_TERMINAL", "Shift is RECONCILED")
    if shift["status"] != "LOCKED":
        raise err("ERR_INVALID_STATE",
                  f"Cannot reconcile a shift in {shift['status']}")
    for asg in db["assignments"].values():
        if asg["shift_id"] != shift["id"]:
            continue
        if asg["status"] == "CONFIRMED":
            asg["status"] = "COMPLETED"
            mark_dirty("assignments", asg["id"])
        elif asg["status"] == "SCHEDULED":
            asg["status"] = "NO_SHOW"
            mark_dirty("assignments", asg["id"])
    shift["status"] = "RECONCILED"
    mark_dirty("shifts", shift["id"])
    return success(ser.shift(shift))


@bp.post("/fleet/shifts/<sid>/assignments")
def create_assignment(sid):
    require_roles("MaintenanceSupervisor")
    shift = get_shift_or_404(sid)
    data = body()
    mechanic_id = data.get("mechanic_id")
    if mechanic_id is not None and mechanic_id not in db["mechanics"]:
        raise err("ERR_NOT_FOUND", f"Mechanic {mechanic_id} not found")
    if mechanic_id is None:
        raise err("ERR_VALIDATION", "Missing required field: mechanic_id")
    role_in_shift = req_enum(data, "role_in_shift", dom.SHIFT_ROLES)
    # duplicate check (priority 19)
    for asg in db["assignments"].values():
        if (asg["shift_id"] == shift["id"]
                and asg["mechanic_id"] == mechanic_id
                and asg["status"] != "REMOVED"):
            raise err("ERR_DUPLICATE_ASSIGNMENT",
                      "Mechanic already has a non-REMOVED assignment on this "
                      "shift")
    # half-open interval overlap (priority 22)
    new_start, new_end = dom.shift_absolute_interval(shift)
    for asg in db["assignments"].values():
        if (asg["mechanic_id"] != mechanic_id
                or asg["status"] not in ("SCHEDULED", "CONFIRMED")):
            continue
        other_shift = db["shifts"].get(asg["shift_id"])
        if other_shift is None:
            continue
        o_start, o_end = dom.shift_absolute_interval(other_shift)
        if new_start < o_end and o_start < new_end:
            raise err("ERR_SHIFT_OVERLAP",
                      "Mechanic has an overlapping shift assignment")
    # shift must be PUBLISHED (priority 39)
    if shift["status"] != "PUBLISHED":
        raise err("ERR_SHIFT_NOT_PUBLISHED", "Shift is not PUBLISHED")
    asg = init_common({
        "shift_id": shift["id"],
        "mechanic_id": mechanic_id,
        "role_in_shift": role_in_shift,
        "status": "SCHEDULED",
    })
    db["assignments"][asg["id"]] = asg
    mark_dirty("shifts", shift["id"])  # coverage is derived from assignments
    return success(ser.assignment(asg), code=201)


@bp.get("/fleet/shifts/<sid>/assignments")
def list_shift_assignments(sid):
    require_roles(*ALL)
    get_shift_or_404(sid)
    items = sort_default([a for a in db["assignments"].values()
                          if a["shift_id"] == sid])
    page, meta_p = paginate(items)
    return success([ser.assignment(a) for a in page], response_type="array",
                   pagination=meta_p)


_ASG_EVENTS = {"CONFIRM", "NO_SHOW", "REMOVE"}
_ASG_FROM = {
    "CONFIRM": {"SCHEDULED"},
    "NO_SHOW": {"SCHEDULED", "CONFIRMED"},
    "REMOVE": {"SCHEDULED", "CONFIRMED"},
}


@bp.post("/fleet/shift-assignments/<asg_id>/events")
def assignment_event(asg_id):
    uid, role = require_roles("MaintenanceSupervisor", "Mechanic")
    asg = get_assignment_or_404(asg_id)
    data = body()
    event_type = req_enum(data, "event_type", _ASG_EVENTS)
    # per-event role / ownership gates (priority 2)
    if event_type == "CONFIRM":
        if role == "Mechanic" and uid != asg["mechanic_id"]:
            raise err("ERR_FORBIDDEN",
                      "A mechanic may only confirm their own assignment")
    else:
        if role != "MaintenanceSupervisor":
            raise err("ERR_FORBIDDEN",
                      f"Role {role} may not perform {event_type}")
    if asg["status"] in dom.ASSIGNMENT_TERMINAL:
        raise err("ERR_ALREADY_TERMINAL",
                  f"Assignment is {asg['status']}; transitions are forbidden")
    if asg["status"] not in _ASG_FROM[event_type]:
        raise err("ERR_INVALID_STATE",
                  f"Cannot {event_type} an assignment in {asg['status']}")
    if event_type == "CONFIRM":
        shift = db["shifts"].get(asg["shift_id"])
        if shift is None or shift["status"] != "PUBLISHED":
            raise err("ERR_SHIFT_NOT_PUBLISHED", "Shift is not PUBLISHED")
        asg["status"] = "CONFIRMED"
    elif event_type == "NO_SHOW":
        asg["status"] = "NO_SHOW"
    else:
        asg["status"] = "REMOVED"
    mark_dirty("assignments", asg["id"])
    shift = db["shifts"].get(asg["shift_id"])
    if shift is not None:
        mark_dirty("shifts", shift["id"])
    return success(ser.assignment(asg))
