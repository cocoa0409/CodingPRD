"""The logical-clock test-driving surface (PRD 2.5)."""

from flask import Blueprint

from auth import ALL_ROLES, endpoint
from envelope import ok
from store import clock_now, iso3, set_clock
from validate import Body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(*ALL_ROLES)
def set_current_utc():
    body = Body()
    moment = body.datetime("current_utc", required=True)
    set_clock(moment)
    return ok({"current_utc": iso3(clock_now())})
