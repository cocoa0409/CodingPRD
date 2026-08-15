"""Logical clock test-driving endpoint."""
from db import parse_iso_to_dt, set_logical_clock, now_iso
from errors import ApiError
from middleware import auth
from response import ok
from util import json_body, parse_str_field


def register(app):
    @app.post("/re-underwriting/_clock/set_current_utc")
    def set_current_utc():
        _user_id, _role = auth(allowed=["Admin"])
        body = json_body()
        iso = parse_str_field(body, "to_iso8601")
        dt = parse_iso_to_dt(iso)
        if dt is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "to_iso8601 is not a valid ISO 8601 timestamp"
            )
        set_logical_clock(dt)
        return ok({"current_utc": now_iso()})
