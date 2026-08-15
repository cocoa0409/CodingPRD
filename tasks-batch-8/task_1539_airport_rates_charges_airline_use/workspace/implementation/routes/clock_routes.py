"""Logical clock test-driving endpoint."""
from flask import Blueprint

import errors
import helpers
from db import store
from response import success_object
from services import automation_sweep
from util import parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/airport/_clock/set_current_utc")
def set_clock():
    helpers.authenticate(("AirportFinance", "AirportDirector"))
    body = helpers.json_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str):
        raise errors.invalid_request("Field 'to_iso8601' is required and must be an ISO 8601 string")
    dt = parse_iso(raw)
    if dt is None:
        raise errors.invalid_request("Field 'to_iso8601' is not a valid ISO 8601 timestamp")
    store.set_clock(raw, dt)
    automation_sweep()
    return success_object({"current_utc": store.clock_iso})
