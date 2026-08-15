"""Logical clock endpoint."""
from flask import Blueprint
from db import store, parse_dt, iso
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success
from services.validators import body, require, check_unknown, to_str
from services.clock_eval import apply_time_transitions

bp = Blueprint("clock", __name__)


@bp.route("/band/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(["BandDirector"])
    data = body()
    check_unknown(data, {"to_iso8601"})
    require(data, "to_iso8601")
    s = to_str(data["to_iso8601"], "to_iso8601")
    try:
        dt = parse_dt(s)
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO8601 datetime")
    store.clock = dt
    apply_time_transitions()
    return success({"current_utc": iso(store.clock)})
