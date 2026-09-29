"""The logical clock capability (PRD 2.4)."""

from flask import Blueprint

import clock
import middleware
import response
import validators

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    middleware.authenticate(middleware.ALL_ROLES)
    body = validators.json_body()
    instant = validators.datetime_field(body, "to_iso8601")
    clock.set_now(instant)
    return response.object_response({"current_utc": clock.now_str()})


@bp.get("/_clock")
def read_clock():
    middleware.authenticate(middleware.ALL_ROLES)
    return response.object_response({"current_utc": clock.now_str()})
