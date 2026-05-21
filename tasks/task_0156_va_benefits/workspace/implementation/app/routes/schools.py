"""School routes."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..errors import ApiError
from ..serializers import serialize_school
from ..services.schools import create_school
from ._common import get_json_body, get_store, respond_object

bp = Blueprint("schools", __name__)


@bp.route("/schools", methods=["POST"])
@require_auth(["PlatformAdmin"])
def post_school():
    body = get_json_body()
    store = get_store()
    with store.lock:
        s = create_school(store, body)
    return respond_object(serialize_school(s), status=201)


@bp.route("/schools/<sid>", methods=["GET"])
@require_auth(["Veteran", "VAClerk", "Counselor", "PlatformAdmin"])
def get_school(sid: str):
    store = get_store()
    s = store.schools.get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", "school not found")
    return respond_object(serialize_school(s))
