"""Logical clock capability (PRD 2.4) — mounted outside /api."""

from flask import request

from db import logical_now, set_logical_now
from middleware import auth, require_role
from response import ok_object
from util import body_dict, parse_dt, render_ts, req


def register(app):
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        auth_user, role = auth()
        require_role(role, {"FoundryAdmin"})
        body = body_dict(request.get_json(silent=True))
        dt = parse_dt(req(body, "to_iso8601"), "to_iso8601")
        set_logical_now(dt)
        return ok_object({"current_utc": render_ts(logical_now())}, 200)
