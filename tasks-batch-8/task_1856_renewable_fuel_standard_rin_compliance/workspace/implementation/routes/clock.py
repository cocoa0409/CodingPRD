"""POST /_clock/set_current_utc — logical clock test-driving endpoint."""
from flask import Blueprint

import db
from errors import invalid_request
from middleware import require_roles, json_body
from response import ok_object
from services import cascade

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("OpsAdmin")
    body = json_body()
    to_iso8601 = body.get("to_iso8601")
    if not to_iso8601 or not isinstance(to_iso8601, str):
        raise invalid_request("to_iso8601 is required")
    try:
        target = db.parse_iso(to_iso8601)
    except (ValueError, TypeError):
        raise invalid_request("to_iso8601 must be a valid ISO 8601 datetime")
    db.set_clock(target)
    # Advancing the clock fires the vintage-expiry sweep and posture re-derivation.
    cascade.vintage_expiry_sweep()
    cascade.rederive_all_postures()
    return ok_object({"current_utc": db.iso(db.now_utc())})
