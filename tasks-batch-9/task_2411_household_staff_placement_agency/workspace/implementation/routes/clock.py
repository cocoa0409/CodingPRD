"""Logical clock endpoints (PRD 2.6).

These two endpoints are exempt from the authentication headers.  The clock only
ever moves forward, and each advance runs the two-part ops sweep.
"""

from flask import Blueprint, request

import db
from errors import fail
from response import object_response
from services.domain import run_ops_sweep
from timeutil import parse_timestamp
from validation import body_of, check_timestamp, require_present

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = body_of(request)
    require_present(body, "current_utc")
    instant = check_timestamp(body, "current_utc")

    if instant < db.store.clock:
        fail("ERR_CLOCK_NOT_MONOTONIC")

    db.store.clock = instant
    db.store.clock_literal = body["current_utc"]

    overdue, expired = run_ops_sweep()
    return object_response(
        {
            "current_utc": db.store.clock_literal,
            "milestones_marked_overdue": overdue,
            "placements_guarantee_expired": expired,
        }
    )


@bp.get("/_clock")
def get_clock():
    return object_response({"current_utc": db.store.clock_literal})
