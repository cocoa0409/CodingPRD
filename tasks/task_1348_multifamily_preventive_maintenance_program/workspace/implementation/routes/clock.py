"""Test-driving logical clock endpoint."""
from flask import Blueprint

import errors as E
from errors import ApiError
from db import set_clock, fmt_clock, parse_dt, now
from middleware import auth, require_role, body, v_str
from response import ok_object
from services.compliance import recompute_all_assets

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth()
    require_role(role, ("PropertyManager",))
    data = body()
    raw = v_str(data, "to_iso8601")
    try:
        dt, _ = parse_dt(raw)
    except ValueError:
        raise ApiError(E.ERR_INVALID_REQUEST, 400, "to_iso8601 is not a valid ISO 8601 instant")
    set_clock(dt)
    # Clock move is a system event: recompute every asset's compliance_status.
    recompute_all_assets()
    return ok_object({"current_utc": fmt_clock(now())}, 200)
