"""The logical clock setter (PRD section 2.3)."""

from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import ROLES, get_ts, json_body
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # This endpoint deliberately requires no acting user (priority 10 exempts it).
    role = request.headers.get("X-User-Role")
    if role is not None and role != "" and (role not in ROLES or role != "ProgramAdmin"):
        raise ApiError("ERR_UNAUTHORIZED")
    body = json_body()
    _, parsed = get_ts(body, "current_utc")
    db.clock = parsed
    return object_response({})
