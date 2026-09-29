"""Commissioned field inspectors."""

from flask import Blueprint, request

from db import base_row, by_created_at, db, insert, touch
from errors import ApiError
from middleware import endpoint
from response import object_response, paginate
from routes import lookup
from services import aggregates, constants as C
from validation import INSPECTOR_STATUSES, body, opt_int, req_dt, req_enum, req_id, req_str

bp = Blueprint("inspectors", __name__)


@bp.post("/inspectors")
@endpoint("BoardAdmin")
def create_inspector():
    payload = body()
    badge_number = req_str(payload, "badge_number")
    home_territory_id = req_id(payload, "home_territory_id")
    certification_expires_on = req_dt(payload, "certification_expires_on")
    max_daily_assignments = opt_int(
        payload, "max_daily_assignments", default=C.DEFAULT_MAX_DAILY_ASSIGNMENTS, minimum=1
    )

    lookup.territory(home_territory_id)

    for existing in db.inspectors.values():
        if existing["badge_number"] == badge_number:
            raise ApiError("ERR_DUPLICATE_BADGE_NUMBER", "badge_number is already on the commission roll.")

    row = base_row()
    row.update(
        {
            "badge_number": badge_number,
            "home_territory_id": home_territory_id,
            "certification_expires_on": certification_expires_on,
            "max_daily_assignments": max_daily_assignments,
            "status": "ACTIVE",
            "active_assignment_count": 0,
        }
    )
    insert(db.inspectors, row)
    return object_response(row, 201)


@bp.get("/inspectors/<inspector_id>")
@endpoint("BoardAdmin", "FieldInspector", "LivestockOwner")
def read_inspector(inspector_id):
    inspector = lookup.inspector(inspector_id)
    aggregates.recompute_inspector_assignments(inspector)
    return object_response(inspector)


@bp.get("/inspectors")
@endpoint("BoardAdmin", "FieldInspector")
def list_inspectors():
    for inspector in db.inspectors.values():
        aggregates.recompute_inspector_assignments(inspector)
    rows = lookup.filtered(
        db.inspectors,
        {
            "home_territory_id": request.args.get("home_territory_id"),
            "status": request.args.get("status"),
        },
    )
    return paginate(by_created_at(rows))


@bp.post("/inspectors/<inspector_id>/status")
@endpoint("BoardAdmin")
def change_inspector_status(inspector_id):
    payload = body()
    new_status = req_enum(payload, "status", INSPECTOR_STATUSES)
    inspector = lookup.inspector(inspector_id)
    inspector["status"] = new_status
    touch(inspector)
    return object_response(inspector)
