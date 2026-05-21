"""Matchup routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import get_json_body, success_response
from core.errors import err_validation
from core.pagination import paginate, parse_pagination
from core.serializers import serialize_entity, serialize_list
from core.utils import lock
from services import matchup_service


bp = Blueprint("matchups", __name__)


def _parse_optional_bool(value):
    if value is None:
        return None
    v = value.lower()
    if v in {"true", "1"}:
        return True
    if v in {"false", "0"}:
        return False
    raise err_validation(f"Invalid boolean: {value}")


@bp.get("/leagues/<league_id>/matchups")
@require_roles("Commissioner", "Manager")
def list_matchups(league_id):
    limit, offset = parse_pagination()
    week_raw = request.args.get("week_number")
    is_playoff = _parse_optional_bool(request.args.get("is_playoff"))
    week_number = None
    if week_raw is not None:
        try:
            week_number = int(week_raw)
        except (TypeError, ValueError):
            raise err_validation("week_number must be an integer.")
    items = matchup_service.list_matchups(
        league_id, week_number=week_number, is_playoff=is_playoff
    )
    sliced, meta = paginate(items, limit, offset)
    return success_response(
        serialize_list(sliced),
        response_type="array",
        pagination=meta,
    )


@bp.post("/leagues/<league_id>/matchups/<int:week_number>/score")
@require_roles("Commissioner")
def score(league_id, week_number):
    with lock():
        body = get_json_body()
        items = matchup_service.score_matchup(league_id, week_number, body)
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
