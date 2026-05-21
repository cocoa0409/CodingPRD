"""Keeper designation routes."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.serializers import serialize_entity, serialize_list
from core.utils import lock
from services import keeper_service


bp = Blueprint("keepers", __name__)


@bp.post("/teams/<team_id>/keepers")
@require_roles("Manager")
def declare(team_id):
    with lock():
        body = get_json_body()
        k = keeper_service.declare_keeper(team_id, body, current_user_id())
        return success_response(serialize_entity(k), status=201)


@bp.get("/teams/<team_id>/keepers")
@require_roles("Commissioner", "Manager")
def list_keepers(team_id):
    items = keeper_service.list_keepers(team_id)
    meta = {
        "limit": 10,
        "offset": 0,
        "total_count": len(items),
        "has_more": False,
    }
    return success_response(
        serialize_list(items),
        response_type="array",
        pagination=meta,
    )


@bp.post("/teams/<team_id>/keepers/<keeper_id>/revoke")
@require_roles("Manager")
def revoke(team_id, keeper_id):
    with lock():
        k = keeper_service.revoke_keeper(team_id, keeper_id, current_user_id())
        return success_response(serialize_entity(k))
