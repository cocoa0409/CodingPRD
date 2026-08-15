"""Logical clock test-driving endpoint."""

from flask import Blueprint

import errors
import middleware
from db import clock, _format_iso, _parse_iso
from helpers import req_datetime
from response import success_object

bp = Blueprint("clock", __name__)


@bp.post("/fundraiser/_clock/set_current_utc")
def set_clock():
    middleware.require_role("FundraiserAdmin")
    from middleware import get_body
    body = get_body(required=True)
    to_dt = req_datetime(body, "to_iso8601")
    clock.set(body["to_iso8601"])
    return success_object({"current_utc": _format_iso(clock.now())}, status=200)
