"""Logical clock test-driving endpoint (PRD 2.6)."""

from flask import Blueprint

import db
from middleware import get_body, require_auth, require_role, validate_body
from response import success_object

bp = Blueprint("clock", __name__)
PREFIX = "/payment-integrity"


@bp.route(PREFIX + "/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    user_id, role = require_auth()
    require_role(role, ["PlanAdmin"])
    body = get_body()
    vals = validate_body(body, {"to_iso8601": (True, "datetime", None)})
    db.set_clock(vals["to_iso8601"])
    return success_object({"current_utc": db.fmt_ts(db.now())})
