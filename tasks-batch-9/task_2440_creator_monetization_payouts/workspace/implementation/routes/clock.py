"""Logical clock (PRD 1.5 rung 3).  The clock is the only time source."""
from flask import Blueprint

from apierrors import fail
from envelope import ok
from fields import F
from gate import endpoint
from store import db, iso

bp = Blueprint("clock", __name__)

FIELDS = (F("to_iso8601", "datetime", required=True),)


@bp.route("/monetization/_clock/set_current_utc", methods=["POST"])
@endpoint(roles=("PlatformAdmin",), fields=FIELDS)
def set_current_utc(ctx):
    target = ctx.data["to_iso8601"]
    if target < db.now:                                            # priority 73
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "The logical clock may never move backwards.")
    db.set_clock(target)
    return ok({"current_utc": iso(db.now)})
