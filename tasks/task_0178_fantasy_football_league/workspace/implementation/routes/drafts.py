"""Draft pick routes."""
from __future__ import annotations

from flask import Blueprint

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_entity, serialize_list
from core.utils import lock
from services import draft_service


bp = Blueprint("drafts", __name__)


@bp.post("/leagues/<league_id>/draft-picks")
@require_roles("Manager")
def submit_pick(league_id):
    with lock():
        body = get_json_body()
        pick = draft_service.submit_pick(league_id, body, current_user_id())
        return success_response(serialize_entity(pick), status=201)


@bp.get("/leagues/<league_id>/draft-picks")
@require_roles("Commissioner", "Manager")
def list_picks(league_id):
    limit, offset = parse_pagination()
    items = draft_service.list_picks(league_id)
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        serialize_list(sliced),
        response_type="array",
        pagination=meta,
    )
