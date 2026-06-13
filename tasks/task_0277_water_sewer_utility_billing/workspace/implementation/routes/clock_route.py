"""Test-driving server clock route (PRD §3.11)."""
from flask import Blueprint

import clock
import middleware
from response import object_response
from services.common import get_json_body, require_datetime

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.require_role({"BillingClerk", "FieldOps", "AssistanceCaseworker"})
    body = get_json_body()
    dt = require_datetime(body, "to_iso8601")
    clock.set_current_utc(dt)
    # Output: null (PRD endpoint table) -> empty data object.
    return object_response({}, 200)
