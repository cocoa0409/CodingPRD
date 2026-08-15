"""Pest treatments: schedule, list, get, drive lifecycle with exclusion windows."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from services import core
from validate import (
    get_body, require_string, require_enum, require_int,
    parse_date_strict, parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("pest_treatments", __name__)

TREATMENT_TYPES = {"ROUTINE", "TARGETED", "FUMIGATION"}
PEST_TARGETS = {"APPLIED", "CLEARED", "CANCELLED"}


def _view(p):
    return {
        "id": p["id"],
        "unit_id": p["unit_id"],
        "treatment_type": p["treatment_type"],
        "scheduled_date": p["scheduled_date"],
        "reentry_buffer_days": p["reentry_buffer_days"],
        "status": p["status"],
        "applied_date": p["applied_date"],
        "exclusion_end_date": p["exclusion_end_date"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/pest-treatments", methods=["POST"])
def create_treatment():
    require_roles("SiteManager")
    body = get_body()
    unit_id = require_string(body, "unit_id")
    treatment_type = require_enum(body, "treatment_type", TREATMENT_TYPES)
    scheduled = parse_date_strict(body.get("scheduled_date"), "scheduled_date")
    buffer_days = require_int(body, "reentry_buffer_days", min_value=0)

    unit = db.units.get(unit_id)
    if unit is None:
        raise err("ERR_UNIT_NOT_FOUND")
    if unit["status"] == "DECOMMISSIONED":
        raise err("ERR_INVALID_STATE", "Cannot create a pest treatment against a DECOMMISSIONED unit")

    now = db.now_ts()
    p = {
        "id": db.new_id(),
        "unit_id": unit_id,
        "treatment_type": treatment_type,
        "scheduled_date": scheduled.isoformat(),
        "reentry_buffer_days": buffer_days,
        "status": "SCHEDULED",
        "applied_date": None,
        "exclusion_end_date": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.pest_treatments[p["id"]] = p
    return success_object(_view(p), status=201)


@bp.route("/pest-treatments", methods=["GET"])
def list_treatments():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.pest_treatments.values())
    unit_f = get_filter("unit_id")
    status_f = get_filter("status")
    if unit_f is not None:
        items = [p for p in items if p["unit_id"] == unit_f]
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(p) for p in page], total, limit, offset)


@bp.route("/pest-treatments/<pid>", methods=["GET"])
def get_treatment(pid):
    get_auth()
    p = db.pest_treatments.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND")
    return success_object(_view(p))


@bp.route("/pest-treatments/<pid>", methods=["PUT"])
def drive_treatment(pid):
    require_roles("SiteManager")
    body = get_body()
    target = require_enum(body, "status", PEST_TARGETS)
    p = db.pest_treatments.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND")
    current = p["status"]
    now = db.now_ts()
    clock_date = clock.current_date()

    unit = db.units.get(p["unit_id"])

    if target == "APPLIED":
        if current != "SCHEDULED":
            raise err("ERR_INVALID_STATE", f"Cannot apply a treatment in {current}")
        if unit is not None and unit["status"] == "DECOMMISSIONED":
            raise err("ERR_INVALID_STATE", "Unit is DECOMMISSIONED")
        p["status"] = "APPLIED"
        p["applied_date"] = clock_date.isoformat()
        p["exclusion_end_date"] = (clock_date + timedelta(days=p["reentry_buffer_days"])).isoformat()
        p["updated_at"] = now
        core.recompute_pest_exclusion(p["unit_id"])

    elif target == "CLEARED":
        if current != "APPLIED":
            raise err("ERR_INVALID_STATE", f"Cannot clear a treatment in {current}")
        if clock_date <= clock.parse_date(p["exclusion_end_date"]):
            raise err("ERR_REENTRY_BUFFER_ACTIVE")
        p["status"] = "CLEARED"
        p["updated_at"] = now
        core.recompute_pest_exclusion(p["unit_id"])

    elif target == "CANCELLED":
        if current != "SCHEDULED":
            raise err("ERR_INVALID_STATE", f"Cannot cancel a treatment in {current}")
        p["status"] = "CANCELLED"
        p["updated_at"] = now

    return success_object(_view(p))
