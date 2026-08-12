"""Administrative logical-clock endpoint (mounted outside /litigation)."""
from flask import Blueprint

import db
from lib import bad_request, body_dict, ok, req_str, require_role

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    b = body_dict()
    raw = req_str(b, "to_iso8601")
    try:
        db.parse_iso(raw)
    except Exception:
        bad_request("to_iso8601 must be an ISO 8601 UTC instant")
    require_role("PlatformAdmin")
    db.clock.set(raw)
    return ok({}, 200)
