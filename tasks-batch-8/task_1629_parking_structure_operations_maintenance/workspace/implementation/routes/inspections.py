"""Structural inspection endpoints (PRD 3.6)."""
from flask import Blueprint, request

import db
from errors import err_invalid_state, err_validation
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.cascade import critical_report_cascade
from services.common import (
    body, require_string, require_datetime, optional_int,
    parse_pagination, paginate, require_ref, get_inspection, public_view,
)
from services.fees import compute_condition

bp = Blueprint("inspections", __name__)


def _rating(payload, name):
    v = payload.get(name)
    if v is None:
        raise err_validation(f"missing required field: {name}")
    if isinstance(v, bool) or not isinstance(v, int) or v < 1 or v > 5:
        raise err_validation(f"{name} must be an integer in 1..5")
    return v


@bp.post("/ops/inspections")
def create_inspection():
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    level_scope = require_string(payload, "level_scope")
    scheduled_for = require_datetime(payload, "scheduled_for")
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "level_scope": level_scope,
        "scheduled_for": db.format_iso(scheduled_for),
        "inspection_status": "SCHEDULED",
        "load_bearing_rating": None,
        "waterproofing_rating": None,
        "surface_rating": None,
        "closed_space_count": 0,
        "condition_index": None,
        "condition_class": None,
    }
    db.stamp_new(ent)
    db.inspections[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/inspections/<inspection_id>")
def get_inspection_route(inspection_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_inspection(inspection_id)))


@bp.get("/ops/inspections")
def list_inspections():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.inspections.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("inspection_status")
    if facility_id is not None:
        items = [i for i in items if i["facility_id"] == facility_id]
    if status is not None:
        items = [i for i in items if i["inspection_status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(i) for i in page], limit, offset, total)


@bp.post("/ops/inspections/<inspection_id>/start")
def start_inspection(inspection_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    insp = get_inspection(inspection_id)
    if insp["inspection_status"] != "SCHEDULED":
        raise err_invalid_state("only a SCHEDULED inspection may start fieldwork")
    insp["inspection_status"] = "IN_FIELD"
    db.touch(insp)
    return success_object(public_view(insp))


@bp.post("/ops/inspections/<inspection_id>/report")
def report_inspection(inspection_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    insp = get_inspection(inspection_id)
    payload = body()
    lb = _rating(payload, "load_bearing_rating")
    wp = _rating(payload, "waterproofing_rating")
    sf = _rating(payload, "surface_rating")
    closed = optional_int(payload, "closed_space_count", default=0, minimum=0)
    if insp["inspection_status"] != "IN_FIELD":
        raise err_invalid_state("only an IN_FIELD inspection may be reported")
    index, klass = compute_condition(lb, wp, sf)
    insp["load_bearing_rating"] = lb
    insp["waterproofing_rating"] = wp
    insp["surface_rating"] = sf
    insp["closed_space_count"] = closed
    insp["condition_index"] = index
    insp["condition_class"] = klass
    insp["inspection_status"] = "REPORTED"
    db.touch(insp)
    if klass == "CRITICAL":
        facility = db.facilities[insp["facility_id"]]
        critical_report_cascade(facility, closed)
    return success_object(public_view(insp))


@bp.post("/ops/inspections/<inspection_id>/cancel")
def cancel_inspection(inspection_id):
    actor = get_actor()
    require_roles(actor, ["MaintenanceSupervisor"])
    insp = get_inspection(inspection_id)
    if insp["inspection_status"] not in ("SCHEDULED", "IN_FIELD"):
        raise err_invalid_state("only a SCHEDULED or IN_FIELD inspection may be cancelled")
    insp["inspection_status"] = "CANCELLED"
    db.touch(insp)
    return success_object(public_view(insp))
