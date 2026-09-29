"""Logical clock control (PRD 2.4)."""
from flask import Blueprint

from db import db
from middleware import endpoint
from response import obj_response
from validate import body, v_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["AccessibilityLead"])
def set_clock():
    data = body()
    _raw, parsed = v_datetime(data, "to_iso8601", required=True)
    # a pure control operation: no writes, no recomputation
    db.clock = parsed
    return obj_response({})
