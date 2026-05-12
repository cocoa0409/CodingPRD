"""PointsTransaction read-only endpoint."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from db import db
from errors import ERR_FORBIDDEN, raise_api_error
from middleware import require_roles
from response import list_response
from services.common import (
    paginate,
    parse_iso8601_utc,
    parse_pagination,
)
from services.lookup import get_household, get_resident_by_id

bp = Blueprint("points_transactions", __name__)


@bp.get("/communities/<community_id>/households/<household_id>/points-transactions")
@require_roles("CommunityAdmin", "Resident")
def list_transactions(community_id: str, household_id: str):
    get_household(community_id, household_id)
    if g.user_role == "Resident":
        me = get_resident_by_id(g.user_id)
        if me is None or me.get("household_id") != household_id:
            raise_api_error(ERR_FORBIDDEN, "Resident does not own this household.")

    limit, offset = parse_pagination()
    kind = request.args.get("kind")
    from_raw = request.args.get("from")
    to_raw = request.args.get("to")
    from_utc = parse_iso8601_utc(from_raw) if from_raw else None
    to_utc = parse_iso8601_utc(to_raw) if to_raw else None

    items = []
    for t in db.points_transactions.values():
        if t["household_id"] != household_id:
            continue
        if kind is not None and t["kind"] != kind:
            continue
        t_time = parse_iso8601_utc(t["created_at"])
        if from_utc is not None and t_time < from_utc:
            continue
        if to_utc is not None and t_time >= to_utc:
            continue
        items.append(t)
    items.sort(key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return jsonify(list_response(page, limit, offset, total)), 200
