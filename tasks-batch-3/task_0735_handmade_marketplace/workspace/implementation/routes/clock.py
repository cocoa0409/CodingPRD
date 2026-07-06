"""Logical clock endpoint."""
from flask import Blueprint
from auth import get_auth, require_role
from db import parse_iso, set_clock
from envelope import success
from errors import raise_err, ERR_VALIDATION
from helpers import get_json_body, require_field

bp = Blueprint("clock", __name__)


@bp.route("/seller/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    ts_s = require_field(body, "to_iso8601", str)
    try:
        dt = parse_iso(ts_s)
    except Exception:
        raise_err(ERR_VALIDATION, "invalid ISO timestamp")
    set_clock(dt)
    return success({})
