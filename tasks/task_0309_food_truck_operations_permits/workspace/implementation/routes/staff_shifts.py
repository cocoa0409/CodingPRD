"""StaffShift endpoints (PRD §3.8)."""

import datetime

from flask import request, Blueprint

import errors
import serializers
import services
from db import db
from clock import parse_iso
from errors import err
from helpers import (get_body, require_str, require_fk, require_enum,
                     require_datetime, get_pagination, paginate)
from lookups import get_staff_shift, get_truck
from middleware import require_user_context, require_role, require_truck_ownership
from response import ok_object, ok_array

bp = Blueprint("staff_shifts", __name__)

WRITE_ROLES = {"OperatorTruck", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}
SHIFT_ROLES = {"DRIVER", "COOK", "CASHIER"}


@bp.post("/staff-shifts")
def create_staff_shift():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    # FK existence (priority 4) before other well-formedness (priority 5).
    truck_id = require_fk(body, "truck_id")
    get_truck(truck_id)
    require_truck_ownership(user_id, role, truck_id)
    staff_name = require_str(body, "staff_name")
    shift_role = require_enum(body, "role", SHIFT_ROLES)
    shift_start = require_datetime(body, "shift_start")
    shift_end = require_datetime(body, "shift_end")
    if not (shift_end > shift_start):
        raise err(errors.ERR_INVALID_REQUEST, "shift_end must be after shift_start")
    # Priority 12: overlap with existing SCHEDULED shift for same (truck, name).
    for sh in db.staff_shifts.values():
        if sh["truck_id"] != truck_id or sh["staff_name"] != staff_name:
            continue
        if sh["status"] != "SCHEDULED":
            continue
        ex_start = parse_iso(sh["shift_start"])
        ex_end = parse_iso(sh["shift_end"])
        # Half-open overlap; adjacency at a shared endpoint is allowed.
        if shift_start < ex_end and ex_start < shift_end:
            raise err(errors.ERR_SHIFT_OVERLAP, "Shift overlaps an existing scheduled shift")
    rec = db.new_record({
        "truck_id": truck_id,
        "staff_name": staff_name,
        "role": shift_role,
        "shift_start": body["shift_start"],
        "shift_end": body["shift_end"],
        "status": "SCHEDULED",
    })
    db.staff_shifts[rec["id"]] = rec
    truck = db.trucks.get(truck_id)
    if truck is not None:
        services.recompute_operability(truck)
    return ok_object(serializers.staff_shift(rec), 201)


@bp.get("/staff-shifts")
def list_staff_shifts():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    records = list(db.staff_shifts.values())
    truck_id = request.args.get("truck_id")
    if truck_id is not None:
        records = [r for r in records if r["truck_id"] == truck_id]
    window, total = paginate(records, limit, offset)
    return ok_array([serializers.staff_shift(r) for r in window], limit, offset, total)


@bp.get("/staff-shifts/<shift_id>")
def get_staff_shift_route(shift_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_staff_shift(shift_id)
    return ok_object(serializers.staff_shift(rec))


@bp.post("/staff-shifts/<shift_id>/cancel")
def cancel_staff_shift(shift_id):
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    rec = get_staff_shift(shift_id)
    require_truck_ownership(user_id, role, rec["truck_id"])
    if rec["status"] != "SCHEDULED":
        raise err(errors.ERR_SHIFT_NOT_SCHEDULED, "Shift is not SCHEDULED")
    rec["status"] = "CANCELLED"
    db.touch(rec)
    truck = db.trucks.get(rec["truck_id"])
    if truck is not None:
        services.recompute_operability(truck)
    return ok_object(serializers.staff_shift(rec))
