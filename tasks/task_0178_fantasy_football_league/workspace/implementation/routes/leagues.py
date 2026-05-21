"""League routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import current_user_id, require_roles
from core.envelope import get_json_body, success_response
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_entity, serialize_list
from core.utils import lock
from services import league_service, waiver_service


bp = Blueprint("leagues", __name__)


@bp.post("/leagues")
@require_roles("Commissioner")
def create_league():
    with lock():
        body = get_json_body()
        league = league_service.create_league(body)
        return success_response(serialize_entity(league), status=201)


@bp.get("/leagues/<league_id>")
@require_roles("Commissioner", "Manager")
def get_league(league_id):
    league = league_service.get_league(league_id)
    return success_response(serialize_entity(league))


@bp.post("/leagues/<league_id>/start-draft")
@require_roles("Commissioner")
def start_draft(league_id):
    with lock():
        league = league_service.start_draft(league_id)
        return success_response(serialize_entity(league))


@bp.post("/leagues/<league_id>/finish-draft")
@require_roles("Commissioner")
def finish_draft(league_id):
    with lock():
        league = league_service.finish_draft(league_id)
        return success_response(serialize_entity(league))


@bp.post("/leagues/<league_id>/archive")
@require_roles("Commissioner")
def archive_league(league_id):
    with lock():
        league = league_service.archive_league(league_id)
        return success_response(serialize_entity(league))


@bp.post("/leagues/<league_id>/_clock/advance")
@require_roles("Commissioner")
def advance_clock(league_id):
    with lock():
        body = get_json_body()
        league = league_service.advance_clock(league_id, body)
        return success_response(serialize_entity(league))


@bp.post("/leagues/<league_id>/_waivers/process")
@require_roles("Commissioner")
def waivers_process(league_id):
    with lock():
        awarded = waiver_service.process_now(league_id)
        # Return all PROCESSED claims (awarded + lost) — convention: return any claims touched
        # Per scaffold output: WaiverClaim[]
        from core.store import store
        all_claims = [
            c
            for c in store.waiver_claims.values()
            if c["league_id"] == league_id
        ]
        all_claims.sort(key=lambda x: x["created_at"])
        limit, offset = 10, 0
        # No pagination params on this endpoint per scaffold; return as array
        meta = {
            "limit": limit,
            "offset": offset,
            "total_count": len(all_claims),
            "has_more": False,
        }
        return success_response(
            serialize_list(all_claims),
            response_type="array",
            pagination=meta,
        )
