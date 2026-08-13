"""Logical clock endpoint (PRD §2.6)."""

from flask import request

from db import set_logical_clock
from middleware import endpoint
from response import ok_object
from routes import bp
from util import body_dict, iso_z, parse_dt, req_present


@bp.route("/plant/_clock/set_current_utc", methods=["POST"])
@endpoint({"PlantManager"})
def set_clock(user_id, role):
    body = body_dict(request.get_json(silent=True))
    dt = parse_dt(req_present(body, "to_iso8601"), "to_iso8601")
    set_logical_clock(dt)
    from db import logical_now

    return ok_object({"current_utc": iso_z(logical_now())})
