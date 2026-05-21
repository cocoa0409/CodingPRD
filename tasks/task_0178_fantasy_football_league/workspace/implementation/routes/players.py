"""Player catalog routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import get_json_body, success_response
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_entity, serialize_list
from core.utils import lock
from services import player_service


bp = Blueprint("players", __name__)


@bp.post("/players")
@require_roles("Commissioner")
def create_player():
    with lock():
        body = get_json_body()
        p = player_service.create_player(body)
        return success_response(serialize_entity(p), status=201)


@bp.get("/players")
@require_roles("Commissioner", "Manager")
def list_players():
    limit, offset = parse_pagination()
    position = request.args.get("position")
    status_tag = request.args.get("status_tag")
    items = player_service.list_players(position=position, status_tag=status_tag)
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        serialize_list(sliced),
        response_type="array",
        pagination=meta,
    )


@bp.post("/players/<player_id>/status")
@require_roles("Commissioner")
def update_status(player_id):
    with lock():
        body = get_json_body()
        p = player_service.update_player_status(player_id, body)
        return success_response(serialize_entity(p))
