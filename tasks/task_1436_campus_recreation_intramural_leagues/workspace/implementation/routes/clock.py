"""Administrator test-driving logical clock."""

from flask import Blueprint

import errors as E
from store import DB
from util import body_json, envelope_object, require_role, fmt_dt, parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/v1/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role("RecAdmin")
    body = body_json()
    raw = body.get("to_iso8601")
    if raw is None:
        raise E.err_validation("Missing required field: to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise E.err_validation("to_iso8601 must be an ISO 8601 UTC datetime")
    DB.clock = dt
    return envelope_object({"current_utc": fmt_dt(DB.clock)})
