"""Defect endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import (
    err_validation, err_state_transition, err_interval_in_past,
    err_deferral_limit_exceeded,
)
from services.common import (
    body, require_string, require_enum, parse_datetime_field, parse_pagination,
    paginate, get_asset, get_defect,
)
from services.calculations import compute_defect_due_date, refresh_asset_condition_and_due

bp = Blueprint("defects", __name__)

SEVERITY_ENUM = {"C1", "C2", "C3"}


def defect_view(d):
    return {
        "id": d["id"],
        "asset_id": d["asset_id"],
        "test_event_id": d.get("test_event_id"),
        "title": d["title"],
        "description": d["description"],
        "severity": d["severity"],
        "status": d["status"],
        "deferral_count": d.get("deferral_count", 0),
        "deferred_until": d.get("deferred_until"),
        "due_date": d.get("due_date"),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


@bp.post("/defects")
def create_defect():
    actor = get_actor()
    require_roles(actor, ["Technician"])
    payload = body()
    asset_id = require_string(payload, "asset_id")
    title = require_string(payload, "title")
    description = require_string(payload, "description")
    severity = require_enum(payload, "severity", SEVERITY_ENUM)

    # FK
    get_asset(asset_id)

    ent = {
        "id": db.new_id(),
        "asset_id": asset_id,
        "test_event_id": None,
        "title": title,
        "description": description,
        "severity": severity,
        "status": "OPEN",
        "deferral_count": 0,
        "deferred_until": None,
        "due_date": None,
    }
    db.stamp_new(ent)
    ent["due_date"] = compute_defect_due_date(ent["created_at"], severity)
    db.defects[ent["id"]] = ent

    # Recompute condition score
    refresh_asset_condition_and_due(asset_id)

    return success_object(defect_view(ent), status=201)


@bp.get("/defects")
def list_defects():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.defects.values())
    asset_id = request.args.get("asset_id")
    if asset_id:
        items = [d for d in items if d["asset_id"] == asset_id]
    test_event_id = request.args.get("test_event_id")
    if test_event_id:
        items = [d for d in items if d.get("test_event_id") == test_event_id]
    status = request.args.get("status")
    if status:
        items = [d for d in items if d["status"] == status]
    severity = request.args.get("severity")
    if severity:
        items = [d for d in items if d["severity"] == severity]
    page, total = paginate(items, limit, offset)
    return success_list([defect_view(d) for d in page], limit, offset, total)


@bp.get("/defects/<id>")
def get_defect_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    d = get_defect(id)
    return success_object(defect_view(d))


@bp.post("/defects/<id>/defer")
def defer_defect(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    d = get_defect(id)
    payload = body()
    deferred_until_raw = parse_datetime_field(payload, "deferred_until", required=True)

    if d["status"] != "OPEN":
        raise err_state_transition("Defect is not OPEN")
    if d.get("deferral_count", 0) >= 2:
        raise err_deferral_limit_exceeded()
    now = db.now_dt()
    if deferred_until_raw <= now:
        raise err_interval_in_past()

    d["status"] = "DEFERRED"
    d["deferral_count"] = d.get("deferral_count", 0) + 1
    d["deferred_until"] = db._format_iso(deferred_until_raw)
    db.touch(d)

    # Recompute condition score (defect still counts while DEFERRED)
    refresh_asset_condition_and_due(d["asset_id"])

    return success_object(defect_view(d))
