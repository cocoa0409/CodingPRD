"""Logical clock endpoints (PRD §2.4)."""
from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from routes.common import get_json_body, require_str
from services import churn

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("CarrierAdmin")
    body = get_json_body()
    to_iso = require_str(body, "to_iso8601")
    # Validate ISO parseability
    try:
        dt = db.parse_iso(to_iso)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO-8601 instant", 400)
    db.set_clock(to_iso)
    # Side effect: re-run churn evaluation for every producer
    churn.evaluate_all_producers()
    return success_object({"current_utc": db.fmt_iso(dt)}, 200)
