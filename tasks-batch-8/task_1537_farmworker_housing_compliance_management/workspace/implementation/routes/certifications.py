"""Unit certifications: schedule, list, get, drive lifecycle."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from services import core
from validate import (
    get_body, require_string, require_enum, optional_int, optional_string,
    parse_pagination, get_filter, sort_and_paginate,
)

bp = Blueprint("certifications", __name__)


def _view(c):
    return {
        "id": c["id"],
        "unit_id": c["unit_id"],
        "inspector_id": c["inspector_id"],
        "status": c["status"],
        "deficiency_count": c["deficiency_count"],
        "notes": c["notes"],
        "inspection_date": c["inspection_date"],
        "expiry_date": c["expiry_date"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/unit-certifications", methods=["POST"])
def create_cert():
    user_id, _ = require_roles("ComplianceInspector")
    body = get_body()
    unit_id = require_string(body, "unit_id")
    notes = optional_string(body, "notes")
    unit = db.units.get(unit_id)
    if unit is None:
        raise err("ERR_UNIT_NOT_FOUND")
    now = db.now_ts()
    c = {
        "id": db.new_id(),
        "unit_id": unit_id,
        "inspector_id": user_id,
        "status": "SCHEDULED",
        "deficiency_count": 0,
        "notes": notes,
        "inspection_date": None,
        "expiry_date": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.certifications[c["id"]] = c
    return success_object(_view(c), status=201)


@bp.route("/unit-certifications", methods=["GET"])
def list_certs():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.certifications.values())
    unit_f = get_filter("unit_id")
    status_f = get_filter("status")
    if unit_f is not None:
        items = [c for c in items if c["unit_id"] == unit_f]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view(c) for c in page], total, limit, offset)


@bp.route("/unit-certifications/<cid>", methods=["GET"])
def get_cert(cid):
    get_auth()
    c = db.certifications.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND")
    return success_object(_view(c))


@bp.route("/unit-certifications/<cid>", methods=["PUT"])
def drive_cert(cid):
    require_roles("ComplianceInspector")
    body = get_body()
    target = require_enum(body, "status", {"IN_PROGRESS", "PASSED", "FAILED", "VOIDED"})
    c = db.certifications.get(cid)
    if c is None:
        raise err("ERR_NOT_FOUND")
    unit = db.units.get(c["unit_id"])
    clock_date = clock.current_date()
    now = db.now_ts()
    current = c["status"]

    if target == "IN_PROGRESS":
        if current == "SCHEDULED":
            if unit is not None and unit["status"] == "DECOMMISSIONED":
                raise err("ERR_INVALID_STATE", "Unit is DECOMMISSIONED")
        elif current == "FAILED":
            # Zero non-terminal CRITICAL work orders on the unit.
            if core.any_open_critical(c["unit_id"]):
                raise err("ERR_OPEN_WORK_ORDERS_REMAIN")
        else:
            raise err("ERR_INVALID_STATE", f"Cannot move certification from {current} to IN_PROGRESS")
        c["status"] = "IN_PROGRESS"

    elif target == "PASSED":
        if current != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", f"Cannot move certification from {current} to PASSED")
        deficiency = body.get("deficiency_count")
        if deficiency is None:
            raise err("ERR_INVALID_REQUEST", "deficiency_count is required on PASSED")
        if isinstance(deficiency, bool) or not isinstance(deficiency, int) or deficiency < 0:
            raise err("ERR_INVALID_REQUEST", "deficiency_count must be a non-negative integer")
        c["status"] = "PASSED"
        c["deficiency_count"] = deficiency
        c["inspection_date"] = clock_date.isoformat()
        c["expiry_date"] = (clock_date + timedelta(days=core.CERT_VALID_DAYS)).isoformat()
        if "notes" in body:
            c["notes"] = optional_string(body, "notes")
        if unit is not None and unit["status"] == "REGISTERED":
            unit["status"] = "CERTIFIED"
            unit["updated_at"] = now

    elif target == "FAILED":
        if current != "IN_PROGRESS":
            raise err("ERR_INVALID_STATE", f"Cannot move certification from {current} to FAILED")
        deficiency = body.get("deficiency_count")
        if deficiency is None:
            raise err("ERR_INVALID_REQUEST", "deficiency_count is required on FAILED")
        if isinstance(deficiency, bool) or not isinstance(deficiency, int) or deficiency < 0:
            raise err("ERR_INVALID_REQUEST", "deficiency_count must be a non-negative integer")
        c["status"] = "FAILED"
        c["deficiency_count"] = deficiency
        c["inspection_date"] = clock_date.isoformat()
        c["expiry_date"] = None
        if "notes" in body:
            c["notes"] = optional_string(body, "notes")

    elif target == "VOIDED":
        if current != "PASSED":
            raise err("ERR_INVALID_STATE", f"Cannot move certification from {current} to VOIDED")
        c["status"] = "VOIDED"
        if "notes" in body:
            c["notes"] = optional_string(body, "notes")
        # Collapse unit standing if no other valid PASSED cert.
        if unit is not None:
            if not core.unit_has_valid_certification(unit["id"]):
                if unit["status"] == "CERTIFIED":
                    unit["status"] = "REGISTERED"
                    unit["updated_at"] = now
                elif unit["status"] == "OCCUPIED":
                    unit["status"] = "HABITABILITY_HOLD"
                    unit["updated_at"] = now

    c["updated_at"] = now
    if unit is not None:
        core.recompute_site_posture(unit["site_id"])
    return success_object(_view(c))
