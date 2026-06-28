"""WalkIn endpoints (PRD §3.7)."""
from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import models
from errors import err
from response import object_response, array_response
from services import core

bp = Blueprint("walk_ins", __name__)


@bp.post("/studio-ops/walk-ins")
def register_walk_in():
    middleware.authenticate()
    middleware.require_roles("FrontDesk", "StudioManager", "PlatformAdmin")
    body = helpers.get_json_body()
    event_id = helpers.as_str(body, "event_id")
    party_name = helpers.as_str(body, "party_name")
    party_size = helpers.as_int(body, "party_size", min_value=1)
    include_kit = helpers.as_bool(body, "include_supply_kit", required=False, default=False)

    # Priority 5: body FK existence.
    event = db.events.get(event_id)
    if not event:
        raise err(errors.ERR_REFERENCE_NOT_FOUND, "event_id does not exist")
    # Priority 7: parent event OPEN/FULL.
    if event["status"] not in {"OPEN", "FULL"}:
        raise err(errors.ERR_INVALID_STATE, "Event is not OPEN/FULL")
    # Priority 16: seat capacity.
    if party_size > event["seats_available"]:
        raise err(errors.ERR_INSUFFICIENT_SEATS, "party_size exceeds availability")

    rec = models.make_walk_in(event_id, party_name, party_size, include_kit)
    db.walk_ins[rec["id"]] = rec

    core.recompute_seat_ledger(event)
    core.apply_full_flip(event)
    models.touch(event)
    return object_response(models.serialize_walk_in(rec), 201)


@bp.get("/studio-ops/walk-ins/<wid>")
def get_walk_in(wid):
    middleware.authenticate()
    middleware.require_roles("FrontDesk", "StudioManager", "PlatformAdmin")
    rec = db.walk_ins.get(wid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Walk-in not found")
    return object_response(models.serialize_walk_in(rec), 200)


@bp.get("/studio-ops/walk-ins")
def list_walk_ins():
    middleware.authenticate()
    middleware.require_roles("FrontDesk", "StudioManager", "PlatformAdmin")
    limit, offset = helpers.parse_pagination()
    event_id = request.args.get("event_id")
    status = request.args.get("status")
    rows = list(db.walk_ins.values())
    if event_id:
        rows = [r for r in rows if r["event_id"] == event_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = helpers.sort_and_page(rows, limit, offset)
    return array_response([models.serialize_walk_in(r) for r in page],
                          limit, offset, total, 200)


@bp.post("/studio-ops/walk-ins/<wid>/cancel")
def cancel_walk_in(wid):
    middleware.authenticate()
    middleware.require_roles("FrontDesk", "StudioManager", "PlatformAdmin")
    rec = db.walk_ins.get(wid)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Walk-in not found")
    if rec["status"] != "REGISTERED":
        raise err(errors.ERR_INVALID_STATE, "Walk-in is not REGISTERED")
    rec["status"] = "CANCELLED"
    models.touch(rec)

    event = db.events.get(rec["event_id"])
    if event:
        core.recompute_seat_ledger(event)
        core.apply_full_flip(event)
        models.touch(event)
    return object_response(models.serialize_walk_in(rec), 200)
