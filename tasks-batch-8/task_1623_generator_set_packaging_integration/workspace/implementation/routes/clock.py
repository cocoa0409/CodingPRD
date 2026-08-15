"""POST /genset-packaging/_clock/set_current_utc — logical clock control."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp

bp = Blueprint("clock", __name__)


@bp.route("/genset-packaging/_clock/set_current_utc", methods=["POST"])
def set_clock():
    mw.require_roles("PlatformAdmin")
    body = mw.get_json_body()
    to_iso8601 = mw.require_string(body, "to_iso8601")
    db.set_logical_clock_iso(to_iso8601)
    return resp.success_object({}, status_code=200)
