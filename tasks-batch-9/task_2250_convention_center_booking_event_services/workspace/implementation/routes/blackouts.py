"""Maintenance windows and capital project scheduling (PRD 3.10)."""

from flask import Blueprint

import lookups
import validate
from db import db
from errors import err
from middleware import body, endpoint, filter_rows, touch
from response import entity_response
from routes.common import PROJECT_KINDS, body_fk, listing
from services import engine

bp = Blueprint("blackouts", __name__)


@bp.post("/maintenance-blackouts")
@endpoint("FacilitiesPlanner")
def propose_blackout():
    payload = body()
    space = body_fk(payload, "space_id", "space")
    window_start = validate.req_date(payload, "window_start_date")
    window_end = validate.req_date(payload, "window_end_date")
    project_kind = validate.req_enum(payload, "project_kind", PROJECT_KINDS)
    buffer_days = validate.opt_int(payload, "buffer_days", 2, minimum=0)
    if window_end < window_start:
        raise err(
            "ERR_INVALID_REQUEST",
            "Field 'window_end_date' must be on or after 'window_start_date'.",
        )

    blackout = db.insert(
        "blackout",
        {
            "space_id": space["id"],
            "window_start_date": window_start.isoformat(),
            "window_end_date": window_end.isoformat(),
            "buffer_days": buffer_days,
            "project_kind": project_kind,
            "status": "PROPOSED",
        },
    )
    return entity_response(blackout, 201)


@bp.get("/maintenance-blackouts")
@endpoint("VenueAdmin", "FacilitiesPlanner", "SalesManager")
def list_blackouts():
    return listing(filter_rows("blackout", {"space_id": "space_id", "status": "status"}))


@bp.get("/maintenance-blackouts/<blackout_id>")
@endpoint("VenueAdmin", "FacilitiesPlanner", "SalesManager")
def read_blackout(blackout_id):
    return entity_response(lookups.fetch("blackout", blackout_id))


@bp.post("/maintenance-blackouts/<blackout_id>/approve")
@endpoint("FacilitiesPlanner")
def approve_blackout_route(blackout_id):
    blackout = lookups.fetch("blackout", blackout_id)
    if blackout["status"] != "PROPOSED":
        raise err("ERR_BLACKOUT_STATE_INVALID")
    if engine.blackout_conflicts_with_committed_booking(blackout):
        raise err("ERR_MAINTENANCE_BLACKOUT_CONFLICT")
    engine.approve_blackout(blackout)
    return entity_response(blackout)


@bp.post("/maintenance-blackouts/<blackout_id>/defer")
@endpoint("FacilitiesPlanner")
def defer_blackout(blackout_id):
    blackout = lookups.fetch("blackout", blackout_id)
    if blackout["status"] != "PROPOSED":
        raise err("ERR_BLACKOUT_STATE_INVALID")
    blackout["status"] = "DEFERRED"
    touch(blackout)
    return entity_response(blackout)
