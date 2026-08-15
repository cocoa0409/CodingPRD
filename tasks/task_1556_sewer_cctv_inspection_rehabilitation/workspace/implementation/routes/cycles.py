"""InspectionCycle endpoints."""
from flask import Blueprint, request

import db
from db import _parse_iso
from middleware import get_actor, require_roles
from response import success_object, success_list
from errors import err_invalid_request, err_invalid_state, err_conflict, err_not_found
from services.common import (
    body, require_string, parse_datetime_field, parse_pagination, paginate,
    get_district, get_cycle, sweep_notice_expiry,
)

bp = Blueprint("cycles", __name__)

READ_ROLES = ["DistrictEngineer", "Coder", "QaReviewer", "CrewLead"]


def cycle_view(c):
    return {
        "id": c["id"],
        "district_id": c["district_id"],
        "label": c["label"],
        "window_start": c["window_start"],
        "window_end": c["window_end"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.post("/sewer/districts/<id>/inspection-cycles")
def create_cycle(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    district = get_district(id)
    payload = body()
    label = require_string(payload, "label")
    ws = parse_datetime_field(payload, "window_start", required=True)
    we = parse_datetime_field(payload, "window_end", required=True)
    if not (we > ws):
        raise err_invalid_request("window_end must be after window_start")
    ent = {
        "id": db.new_id(),
        "district_id": district["id"],
        "label": label,
        "window_start": db._format_iso(ws),
        "window_end": db._format_iso(we),
        "status": "DRAFT",
    }
    db.stamp_new(ent)
    db.cycles[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(cycle_view(ent), status=201)


@bp.get("/sewer/inspection-cycles/<id>")
def get_cycle_route(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    c = get_cycle(id)
    return success_object(cycle_view(c))


@bp.get("/sewer/districts/<id>/inspection-cycles")
def list_cycles(id):
    actor = get_actor()
    require_roles(actor, READ_ROLES)
    district = get_district(id)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [c for c in db.cycles.values() if c["district_id"] == district["id"]]
    if status_filter:
        items = [c for c in items if c["status"] == status_filter]
    page, total = paginate(items, limit, offset)
    return success_list([cycle_view(c) for c in page], limit, offset, total)


@bp.post("/sewer/inspection-cycles/<id>/open")
def open_cycle(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    c = get_cycle(id)
    if c["status"] != "DRAFT":
        raise err_invalid_state("cycle not in DRAFT")
    ws = _parse_iso(c["window_start"])
    we = _parse_iso(c["window_end"])
    if not (ws < we):
        raise err_invalid_request("window_start must be strictly before window_end")
    # No other OPEN cycle in the same district
    for other in db.cycles.values():
        if other["district_id"] == c["district_id"] and other["id"] != c["id"] and other["status"] == "OPEN":
            raise err_conflict("ERR_CYCLE_OVERLAP", "another cycle in the district is OPEN")
    c["status"] = "OPEN"
    db.touch(c)
    sweep_notice_expiry()
    return success_object(cycle_view(c))


@bp.post("/sewer/inspection-cycles/<id>/close")
def close_cycle(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    c = get_cycle(id)
    if c["status"] != "OPEN":
        raise err_invalid_state("cycle not in OPEN")
    for insp in db.inspections.values():
        if insp["cycle_id"] == c["id"] and insp["status"] not in ("CERTIFIED", "VOIDED"):
            raise err_conflict("ERR_INSPECTIONS_OPEN", "some inspections still open")
    c["status"] = "CLOSED"
    db.touch(c)
    sweep_notice_expiry()
    return success_object(cycle_view(c))
