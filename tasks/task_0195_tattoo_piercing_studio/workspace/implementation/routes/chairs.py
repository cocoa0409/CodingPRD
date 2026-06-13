"""Chair endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import ApiError
from helpers import get_json_body, require_str, paginate
from lookups import get_chair
from middleware import require_auth
from response import success
from serializers import serialize_chair

bp = Blueprint("chairs", __name__)


@bp.route("/studio/chairs", methods=["POST"])
@require_auth(["StudioManager"])
def create_chair():
    body = get_json_body()
    label = require_str(body, "label")

    cleanup = body.get("cleanup_buffer_minutes", 30)
    if cleanup is None:
        cleanup = 30
    if isinstance(cleanup, bool) or not isinstance(cleanup, int):
        raise ApiError("ERR_INVALID_REQUEST", "cleanup_buffer_minutes must be an integer")
    if cleanup < 0:
        raise ApiError("ERR_INVALID_REQUEST", "cleanup_buffer_minutes must be >= 0")

    active = body.get("active", True)
    if active is None:
        active = True
    if not isinstance(active, bool):
        raise ApiError("ERR_INVALID_REQUEST", "active must be a boolean")

    chair = {
        "label": label,
        "cleanup_buffer_minutes": cleanup,
        "active": active,
    }
    db.stamp_create(chair)
    db.chairs[chair["id"]] = chair
    return success(serialize_chair(chair), 201)


@bp.route("/studio/chairs/<chair_id>", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def fetch_chair(chair_id):
    chair = get_chair(chair_id)
    return success(serialize_chair(chair), 200)


@bp.route("/studio/chairs", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_chairs():
    active = request.args.get("active")
    items = list(db.chairs.values())
    if active is not None:
        want = active.lower() in ("true", "1", "yes")
        items = [c for c in items if c["active"] == want]
    page, meta = paginate(items)
    return success([serialize_chair(c) for c in page], 200,
                   response_type="array", pagination=meta)
