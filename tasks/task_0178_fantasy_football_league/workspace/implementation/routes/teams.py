"""Team and roster routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_entity, serialize_list
from core.utils import lock
from services import roster_service, team_service


bp = Blueprint("teams", __name__)


@bp.post("/leagues/<league_id>/teams")
@require_roles("Commissioner")
def create_team(league_id):
    with lock():
        body = get_json_body()
        team = team_service.create_team(league_id, body)
        return success_response(serialize_entity(team), status=201)


@bp.get("/leagues/<league_id>/teams")
@require_roles("Commissioner", "Manager")
def list_teams(league_id):
    limit, offset = parse_pagination()
    items = team_service.list_teams(league_id)
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        serialize_list(sliced),
        response_type="array",
        pagination=meta,
    )


@bp.get("/leagues/<league_id>/teams/<team_id>")
@require_roles("Commissioner", "Manager")
def get_team(league_id, team_id):
    team = team_service.get_team_in_league(league_id, team_id)
    from core.store import store
    out = serialize_entity(team)
    out["roster_slots"] = serialize_list(store.roster_slots_for_team(team_id))
    return success_response(out)


@bp.patch("/teams/<team_id>/roster-slots/<slot_id>")
@require_roles("Manager")
def patch_roster_slot(team_id, slot_id):
    with lock():
        body = get_json_body()
        slot = roster_service.patch_roster_slot(team_id, slot_id, body, current_user_id())
        return success_response(serialize_entity(slot))
