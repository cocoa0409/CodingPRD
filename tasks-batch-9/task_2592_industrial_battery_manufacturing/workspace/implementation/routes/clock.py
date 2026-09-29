"""Logical clock control (PRD 2.4)."""
from flask import Blueprint, g, request

from authz import ALL_ROLES, endpoint
from response import object_response
from store import db
from util import parse_ts

bp = Blueprint("clock", __name__)

CLOCK_SPEC = {"current_utc": {"type": "datetime", "required": True}}


@bp.post("/_clock/set_current_utc")
@endpoint(ALL_ROLES, body=CLOCK_SPEC)
def set_current_utc():
    db.set_clock(g.body["current_utc"])
    supplied = (request.get_json(silent=True) or {}).get("current_utc")
    return object_response({"current_utc": supplied})
