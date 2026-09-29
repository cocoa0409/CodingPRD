"""The /_clock test-driving namespace (PRD section 2.5)."""
from flask import Blueprint

from auth import guard
from cascades import run_sweep
from common import ALL_READ_ROLES
from envelope import respond_object
from errors import ApiError
from store import db, iso, now
from validation import check_body, field

bp = Blueprint("clock", __name__)


def clock_view():
    return {
        "current_utc": iso(db.clock["current_utc"]),
        "set_count": db.clock["set_count"],
    }


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    guard(["NetworkAdmin"])
    body = check_body({"to_iso8601": field("datetime", required=True)})
    target = body["to_iso8601"]

    # instants are compared at whole-second resolution (PRD 2.6)
    if target.replace(microsecond=0) <= now().replace(microsecond=0):
        raise ApiError(
            "ERR_CLOCK_MUST_MOVE_FORWARD", "logical time may only move forward"
        )

    db.clock["current_utc"] = target
    db.clock["set_count"] += 1
    run_sweep()
    return respond_object(clock_view())


@bp.route("/_clock", methods=["GET"])
def read_clock():
    guard(ALL_READ_ROLES)
    return respond_object(clock_view())
