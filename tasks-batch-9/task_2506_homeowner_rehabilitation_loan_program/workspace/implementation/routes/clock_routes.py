"""Logical clock control (PRD 2.6)."""

from flask import Blueprint

import clock
import middleware
import response
import validation
from routes import API_PREFIX

bp = Blueprint("clock_routes", __name__)


@bp.post(API_PREFIX + "/_clock/set_current_utc")
@middleware.roles(*middleware.STAFF_ROLES)
def set_current_utc():
    body = validation.json_body()
    moment = validation.field_datetime(body, "now")
    clock.set_now(moment)
    return response.object_response({"now": clock.iso(moment)}, 200)
