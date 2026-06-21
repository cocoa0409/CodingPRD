"""Flat RosterSlot reverse-reachability endpoints."""
from flask import Blueprint, request

from db import store
from middleware import require_role
from response import success_array, success_object
from services.common import (
    get_roster_slot,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)

bp = Blueprint("roster_slots", __name__)


@bp.route("/roster-slots/<sid>", methods=["GET"])
def get_roster_slot_endpoint(sid):
    require_role("Commissioner", "TeamOwner")
    return success_object(serialize(get_roster_slot(sid)))


@bp.route("/roster-slots", methods=["GET"])
def list_roster_slots():
    require_role("Commissioner", "TeamOwner")
    limit, offset = parse_pagination()
    items = list(store().roster_slots.values())
    team_id = request.args.get("team_id")
    player_id = request.args.get("player_id")
    slot_type = request.args.get("slot_type")
    if team_id is not None:
        items = [s for s in items if s["team_id"] == team_id]
    if player_id is not None:
        items = [s for s in items if s["player_id"] == player_id]
    if slot_type is not None:
        items = [s for s in items if s["slot_type"] == slot_type]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)
