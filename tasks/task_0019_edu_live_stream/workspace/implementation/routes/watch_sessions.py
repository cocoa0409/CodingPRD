"""WatchSession endpoint."""
from flask import Blueprint, request

from db import make_immutable_fields, store
from errors import raise_api
from middleware import require_roles
from response import success
from services.lookup import get_chapter, get_enrollment
from services.progress import recompute_progress

watch_sessions_bp = Blueprint("watch_sessions", __name__)


@watch_sessions_bp.route("/enrollments/<enrollment_id>/watch-sessions", methods=["POST"])
def log_watch_session(enrollment_id):
    user_id, _ = require_roles("Student")
    enr = get_enrollment(enrollment_id)
    if enr["student_id"] != user_id:
        raise_api("ERR_FORBIDDEN_NOT_OWNER", "Not the enrollment owner")
    body = request.get_json(silent=True) or {}
    chapter_id = body.get("chapter_id")
    if not chapter_id:
        raise_api("ERR_CHAPTER_NOT_FOUND", "chapter_id required")
    ch = get_chapter(chapter_id)
    if ch["course_id"] != enr["course_id"]:
        raise_api("ERR_CHAPTER_NOT_FOUND", "Chapter not under this enrollment's course")
    try:
        seconds = int(body["seconds_watched"])
    except (KeyError, TypeError, ValueError):
        raise_api("ERR_INVALID_PRICING", "seconds_watched required")
    if seconds <= 0:
        raise_api("ERR_INVALID_PRICING", "seconds_watched must be > 0")

    ws = {
        **make_immutable_fields(),
        "enrollment_id": enrollment_id,
        "chapter_id": chapter_id,
        "seconds_watched": seconds,
    }
    store.watch_sessions[ws["id"]] = ws
    recompute_progress(enr, run_at_risk=True)
    return success(dict(ws), http_status=201)
