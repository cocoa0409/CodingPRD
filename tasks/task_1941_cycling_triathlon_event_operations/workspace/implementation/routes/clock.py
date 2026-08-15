"""Logical clock endpoint per PRD §2.5."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object
from util import parse_dt, require_fields

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("RaceDirector")
    body = request.get_json(silent=True) or {}
    require_fields(body, ["to_iso8601"])
    # validate parseable
    dt = parse_dt(body["to_iso8601"])
    iso = body["to_iso8601"]
    # Normalize: keep the supplied string but ensure it round-trips
    db.set_clock(iso)
    return success_object({"current_utc": db.get_clock()})
