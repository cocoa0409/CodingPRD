"""Visit endpoints: add to work order, complete, skip, fetch."""
from flask import Blueprint

import errors
from db import db, base_fields, public, touch
from middleware import get_identity, require_role
from response import success, list_success
from validation import (get_json_body, require_int, require_number,
                        parse_pagination, paginate)

bp = Blueprint("visits", __name__)


def _get_wo_or_404(wo_id):
    rec = db.work_orders.get(wo_id)
    if rec is None:
        raise errors.not_found("Work order not found")
    return rec


def _get_visit_or_404(visit_id):
    rec = db.visits.get(visit_id)
    if rec is None:
        raise errors.not_found("Visit not found")
    return rec


@bp.post("/work-orders/<id>/visits")
def add_visit(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    _get_wo_or_404(id)
    body = get_json_body()
    stop_sequence = require_int(body, "stop_sequence", minimum=1)
    leg_distance_km = require_number(body, "leg_distance_km", minimum=0)
    on_site_minutes = require_int(body, "on_site_minutes", minimum=0)

    rec = base_fields()
    rec.update({
        "work_order_id": id,
        "stop_sequence": stop_sequence,
        "leg_distance_km": leg_distance_km,
        "on_site_minutes": on_site_minutes,
        "actual_minutes": None,
        "visit_status": "PLANNED",
    })
    db.visits[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/work-orders/<id>/visits")
def list_visits(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    _get_wo_or_404(id)
    limit, offset = parse_pagination()
    records = [v for v in db.visits.values() if v["work_order_id"] == id]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/visits/<id>")
def get_visit(id):
    _, role = get_identity()
    require_role(role, ["AccountManager", "FieldSupervisor", "PlatformAdmin"])
    rec = _get_visit_or_404(id)
    return success(public(rec))


@bp.post("/visits/<id>/complete")
def complete_visit(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    visit = _get_visit_or_404(id)
    body = get_json_body()
    actual_minutes = require_int(body, "actual_minutes", minimum=0)
    if visit["visit_status"] != "PLANNED":
        raise errors.invalid_state()
    visit["actual_minutes"] = actual_minutes
    visit["visit_status"] = "COMPLETED"
    touch(visit)
    return success(public(visit))


@bp.post("/visits/<id>/skip")
def skip_visit(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor"])
    visit = _get_visit_or_404(id)
    if visit["visit_status"] != "PLANNED":
        raise errors.invalid_state()
    visit["visit_status"] = "SKIPPED"
    touch(visit)
    return success(public(visit))
