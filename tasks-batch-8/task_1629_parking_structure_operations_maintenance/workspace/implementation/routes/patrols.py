"""Patrol round endpoints (PRD 3.7)."""
from flask import Blueprint, request

import db
from errors import err_invalid_state
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_int, optional_int, require_datetime,
    parse_pagination, paginate, require_ref, get_patrol, public_view,
)

bp = Blueprint("patrols", __name__)


@bp.post("/ops/patrol-rounds")
def create_patrol():
    actor = get_actor()
    require_roles(actor, ["SecurityOfficer"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    scheduled_start = require_datetime(payload, "scheduled_start")
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "officer_user_id": actor.user_id,
        "scheduled_start": db.format_iso(scheduled_start),
        "patrol_status": "SCHEDULED",
        "checkpoints_completed": None,
        "lighting_outages_found": 0,
        "completed_at": None,
    }
    db.stamp_new(ent)
    db.patrol_rounds[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/patrol-rounds/<patrol_round_id>")
def get_patrol_route(patrol_round_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_patrol(patrol_round_id)))


@bp.get("/ops/patrol-rounds")
def list_patrols():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.patrol_rounds.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("patrol_status")
    if facility_id is not None:
        items = [p for p in items if p["facility_id"] == facility_id]
    if status is not None:
        items = [p for p in items if p["patrol_status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(p) for p in page], limit, offset, total)


@bp.post("/ops/patrol-rounds/<patrol_round_id>/complete")
def complete_patrol(patrol_round_id):
    actor = get_actor()
    require_roles(actor, ["SecurityOfficer"])
    patrol = get_patrol(patrol_round_id)
    payload = body()
    checkpoints = require_int(payload, "checkpoints_completed", minimum=0)
    outages = optional_int(payload, "lighting_outages_found", default=0, minimum=0)
    if patrol["patrol_status"] != "SCHEDULED":
        raise err_invalid_state("only a SCHEDULED patrol may complete")
    patrol["checkpoints_completed"] = checkpoints
    patrol["lighting_outages_found"] = outages
    patrol["patrol_status"] = "COMPLETED"
    patrol["completed_at"] = db.now_iso()
    db.touch(patrol)
    return success_object(public_view(patrol))
