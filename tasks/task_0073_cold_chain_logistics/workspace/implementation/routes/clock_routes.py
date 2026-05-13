"""Clock fixture endpoints."""

from flask import Blueprint, request

from clock import clock
from errors import err
from middleware import require_roles
from response import object_response
from validators import require_dict, require_number


bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@require_roles("SYSTEM")
def advance():
    body = require_dict(request.get_json(silent=True) or {})
    seconds = body.get("seconds")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        err("ERR_VALIDATION", "seconds must be a number.")
    clock.advance(seconds)
    return object_response({"now": clock.now_iso()}, status_code=200)


@bp.get("/_clock")
@require_roles("SYSTEM")
def get_clock():
    return object_response({"now": clock.now_iso()}, status_code=200)
