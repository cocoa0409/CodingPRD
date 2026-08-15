"""Logical clock endpoint (PRD §2.11)."""

from flask import Blueprint

import db
import errors
import middleware as mw
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    mw.require_roles("TrustAdmin")
    body = mw.get_body()
    mw.require_fields(body, ["to_iso8601"])
    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str):
        raise errors.err_invalid_request("to_iso8601 must be an ISO-8601 string")
    try:
        new_iso = db.set_clock(to_iso)
    except Exception:
        raise errors.err_invalid_request("to_iso8601 must be a valid ISO-8601 instant")
    return success_object({"current_utc": new_iso}, 200)
