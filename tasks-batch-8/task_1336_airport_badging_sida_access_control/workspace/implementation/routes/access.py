"""Door access check endpoints (PRD §3.7)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BADGE_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import logic
from services.serializers import serialize, serialize_list
from util import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    sort_by_created_at,
)

bp = Blueprint("access", __name__)


@bp.route("/access-checks", methods=["POST"])
@require_roles("AccessControlSystem")
def create_access_check(user_id: str, role: str):
    body = get_json_body()
    zone_code = require_enum(body, "zone_code", set(logic.ZONES))

    badge_id = body.get("badge_id")
    if badge_id is not None and not isinstance(badge_id, str):
        raise_err(ERR_INVALID_REQUEST, "badge_id must be a string or null")

    escortee_count = body.get("escortee_count", 0)
    if escortee_count is None:
        escortee_count = 0
    if isinstance(escortee_count, bool) or not isinstance(escortee_count, int):
        raise_err(ERR_INVALID_REQUEST, "escortee_count must be an integer")
    if escortee_count < 0:
        raise_err(ERR_INVALID_REQUEST, "escortee_count must be >= 0")

    badge = None
    if badge_id is not None:
        badge = db.STORES["badges"].get(badge_id)
        if badge is None:
            raise_err(ERR_BADGE_NOT_FOUND, "No badge with the given id")

    decision, denial_reason = logic.access_decide(badge, zone_code, escortee_count)

    now = db.clock_now()
    rec = {
        "badge_id": badge_id,
        "zone_code": zone_code,
        "escortee_count": escortee_count,
        "decision": decision,
        "denial_reason": denial_reason,
        "occurred_at": db.fmt_clock(now),
        "_occurred_dt": now,
    }
    db.stamp_append_only(rec)
    db.STORES["access_events"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.route("/badges/<bid>/access-events", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_access_events(user_id: str, role: str, bid: str):
    fetch_or_404("badges", bid, ERR_BADGE_NOT_FOUND, "badge")
    limit, offset = parse_pagination()
    items = [
        e for e in db.STORES["access_events"].values() if e["badge_id"] == bid
    ]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
