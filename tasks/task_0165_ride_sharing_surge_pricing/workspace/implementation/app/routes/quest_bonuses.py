"""Quest bonus endpoints."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..envelope import paginate, parse_pagination, success_array, success_object
from ..errors import err_invalid_input
from ..serializers import serialize_quest_bonus
from ..store import store
from ..util import new_uuid, parse_iso8601
from ._helpers import (
    filter_by_status,
    get_json,
    get_quest_or_404,
    require_int,
    require_string,
)

bp = Blueprint("quest_bonuses", __name__)


@bp.route("/quest-bonuses", methods=["POST"])
@require_roles(["PlatformAdmin"])
def create_quest_bonus():
    body = get_json()
    name = require_string(body, "name")
    target_ride_count = require_int(body, "target_ride_count", min_value=1)
    bonus_amount_cents = require_int(body, "bonus_amount_cents", min_value=0)
    window_start_s = require_string(body, "window_start")
    window_end_s = require_string(body, "window_end")
    try:
        window_start = parse_iso8601(window_start_s)
        window_end = parse_iso8601(window_end_s)
    except ValueError:
        raise err_invalid_input("window_start/window_end must be ISO 8601 UTC strings")
    if window_end <= window_start:
        # ERR_QUEST_WINDOW_OVERLAP per scaffold validation #12: "window_end > window_start"
        from ..errors import err_quest_window_overlap
        raise err_quest_window_overlap("window_end must be strictly after window_start")

    s = store()
    now = s.now()
    qid = new_uuid()
    q = {
        "id": qid,
        "name": name,
        "target_ride_count": target_ride_count,
        "bonus_amount_cents": bonus_amount_cents,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "bonus_paid": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    # If created with window_start already in the past relative to logical clock,
    # the next /_clock/advance will move it; on creation we leave it SCHEDULED.
    s.insert("quest_bonuses", q)
    return jsonify(success_object(serialize_quest_bonus(q))), 201


@bp.route("/quest-bonuses", methods=["GET"])
@require_roles(["PlatformAdmin", "Driver"])
def list_quest_bonuses():
    limit, offset = parse_pagination()
    items = sorted(store().list_collection("quest_bonuses"), key=lambda x: x["created_at"])
    status = request.args.get("status")
    if status is not None:
        items = filter_by_status(items, status)
    total = len(items)
    page = paginate(items, limit, offset)
    return jsonify(success_array(
        [serialize_quest_bonus(x) for x in page], limit=limit, offset=offset, total_count=total,
    )), 200


@bp.route("/quest-bonuses/<quest_id>", methods=["GET"])
@require_roles(["PlatformAdmin", "Driver"])
def get_quest_bonus(quest_id):
    q = get_quest_or_404(quest_id)
    return jsonify(success_object(serialize_quest_bonus(q))), 200
