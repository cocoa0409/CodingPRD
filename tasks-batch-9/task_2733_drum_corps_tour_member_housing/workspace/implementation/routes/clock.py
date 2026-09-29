"""Logical clock control (PRD 2.10).

Before any call to this endpoint the clock reads exactly 2026-08-01T00:00:00Z;
it never falls back to real wall-clock time.  Setting it mutates no entity and
triggers no sweep.
"""
from flask import Blueprint

import validators as v
from auth import endpoint
from envelope import object_response
from store import db

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["CorpsDirector", "MembershipCoordinator", "TourManager",
           "BusinessManager", "VolunteerScreener"])
def set_current_utc():
    body = v.get_body()
    _raw, parsed = v.req_instant(body, "to_iso8601")
    db.clock = parsed
    return object_response({})
