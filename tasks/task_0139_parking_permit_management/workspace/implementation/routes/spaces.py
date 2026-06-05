"""Space endpoints + space-scoped session list."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_DUPLICATE
from middleware import get_json_body, require_auth
from response import ok_object
from services import recompute
from services.common import list_response, lookup, require_enum, require_string
from services.serialize import public

bp = Blueprint("spaces", __name__)

SPACE_STATUS = {"AVAILABLE", "OUT_OF_SERVICE"}


@bp.post("/parking/spaces")
def create_space():
    require_auth(["FacilityAdmin"])()
    body = get_json_body()
    zone_id = require_string(body, "zone_id")
    label = require_string(body, "label")
    status = require_enum(body, "status", SPACE_STATUS, required=False, default="AVAILABLE")

    zone = lookup(db.zones, zone_id)

    # Uniqueness: label unique within the zone.
    for s in db.spaces.values():
        if s["zone_id"] == zone_id and s["label"] == label:
            raise APIError(ERR_DUPLICATE, 409, "Space label already exists in this zone")

    sp = db.stamp_common(
        {
            "zone_id": zone_id,
            "label": label,
            "status": status,
            "is_occupied": False,
        }
    )
    db.spaces[sp["id"]] = sp

    # Recompute owning garage's total_space_count.
    garage = db.garages.get(zone["garage_id"])
    if garage is not None:
        recompute.recompute_garage_counts(garage, bump=True)

    return ok_object(public(sp), 201)


@bp.get("/parking/spaces/<sid>")
def read_space(sid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    sp = lookup(db.spaces, sid)
    return ok_object(public(sp), 200)


@bp.get("/parking/spaces/<sid>/sessions")
def list_space_sessions(sid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.spaces, sid)
    items = [s for s in db.sessions.values() if s.get("space_id") == sid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, request.args)
