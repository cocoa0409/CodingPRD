"""The logical-clock setter (PRD section 2.4)."""

from flask import Blueprint

import auth
import clock
import response
import validation

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    instant = validation.datetime_field(body, "to_iso8601")
    clock.set_now(instant)
    return response.object_response({"current_utc": clock.now_iso_instant()})
