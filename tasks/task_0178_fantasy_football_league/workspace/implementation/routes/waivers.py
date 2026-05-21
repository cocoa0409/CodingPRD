"""Waiver claim routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_entity, serialize_list
from core.utils import lock
from services import waiver_service


bp = Blueprint("waivers", __name__)


@bp.post("/leagues/<league_id>/waivers")
@require_roles("Manager")
def submit(league_id):
    with lock():
        body = get_json_body()
        claim = waiver_service.submit_claim(league_id, body, current_user_id())
        return success_response(serialize_entity(claim), status=201)


@bp.get("/leagues/<league_id>/waivers")
@require_roles("Commissioner", "Manager")
def list_claims(league_id):
    limit, offset = parse_pagination()
    team_id = request.args.get("team_id")
    status = request.args.get("status")
    items = waiver_service.list_claims(league_id, team_id=team_id, status=status)
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        serialize_list(sliced),
        response_type="array",
        pagination=meta,
    )


@bp.post("/waivers/<waiver_id>/cancel")
@require_roles("Manager")
def cancel(waiver_id):
    with lock():
        claim = waiver_service.cancel_claim(waiver_id, current_user_id())
        return success_response(serialize_entity(claim))
