"""BlackoutWindow routes. PRD §3.11."""
from __future__ import annotations

from flask import Blueprint, request

import db
from common import (
    get_body, pagination_params, paginate_and_sort, require_datetime,
    require_string, stamp_common_fields, touch,
)
from errors import APIError, ERR_INVALID_STATE, ERR_BLACKOUT_OVERLAP, ERR_VALIDATION
from middleware import require_roles
from response import created, success, list_response
from services import core

bp = Blueprint("blackout_windows", __name__)


def _half_open_overlap(a_start, a_end, b_start, b_end) -> bool:
    """HALF-OPEN [a_start,a_end) vs [b_start,b_end): adjacency does NOT conflict."""
    return a_start < b_end and b_start < a_end


@bp.post("/blackout-windows")
@require_roles("Administrator")
def create_blackout():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    core.get_cap_table(cap_table_id)
    reason = require_string(body, "reason", non_empty=True)
    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    if ends_at <= starts_at:
        raise APIError(ERR_VALIDATION, "ends_at must be strictly after starts_at.", 400)

    for w in db.blackout_windows.values():
        if w["cap_table_id"] != cap_table_id or w["status"] != "SCHEDULED":
            continue
        if _half_open_overlap(starts_at, ends_at, w["starts_at"], w["ends_at"]):
            raise APIError(ERR_BLACKOUT_OVERLAP, "Blackout window overlaps a SCHEDULED window.", 409)

    now = db.now_utc()
    w = {
        "cap_table_id": cap_table_id,
        "reason": reason,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
    }
    stamp_common_fields(w, now)
    db.blackout_windows[w["id"]] = w
    return created(core.serialize(w))


@bp.get("/blackout-windows/<cid>")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def get_blackout(cid):
    return success(core.serialize(core.get_blackout(cid)))


@bp.get("/blackout-windows")
@require_roles("Administrator", "BoardApprover", "Auditor", "Stakeholder")
def list_blackouts():
    limit, offset = pagination_params()
    items = list(db.blackout_windows.values())
    cap_table_id = request.args.get("cap_table_id")
    if cap_table_id is not None:
        items = [w for w in items if w["cap_table_id"] == cap_table_id]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(w) for w in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.post("/blackout-windows/<cid>/lift")
@require_roles("Administrator")
def lift_blackout(cid):
    w = core.get_blackout(cid)
    if w["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, "Window must be SCHEDULED to lift.", 409)
    now = db.now_utc()
    w["status"] = "LIFTED"
    touch(w, now)
    return success(core.serialize(w))
