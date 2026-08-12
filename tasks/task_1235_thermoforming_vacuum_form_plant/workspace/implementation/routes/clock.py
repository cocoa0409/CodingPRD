"""Logical clock endpoint (PRD §2.5)."""

from flask import request

from db import set_logical_clock, CLOCK
from middleware import endpoint, ANY_ROLE
from response import ok_object
from util import body_dict, parse_dt, req_present

from routes import bp


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(ANY_ROLE)
def set_clock(user_id, role):
    body = body_dict(request.get_json(silent=True))
    raw = req_present(body, "to_iso8601")
    dt = parse_dt(raw, "to_iso8601")
    set_logical_clock(dt, raw if isinstance(raw, str) else None)
    if CLOCK["raw"] is None:
        from util import iso_z
        CLOCK["raw"] = iso_z(dt)
    return ok_object({"current_utc": CLOCK["raw"]})
