"""Logical-clock test-driving endpoint (PRD 2.4). EHSManager only."""

from flask import Blueprint

from clock import CLOCK, fmt
from middleware import auth
from response import ok
from services import core

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth(["EHSManager"])
    body = core.body_json()
    target = core.req_dt(body, "to_iso8601")
    CLOCK.set(target)
    return ok({"current_utc": fmt(CLOCK.now())})
