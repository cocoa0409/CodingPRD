"""Logical clock driver (PRD 2.5)."""

from flask import Blueprint

from clock import CLOCK, fmt
from middleware import auth
from response import ok
from services import core

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth(["EHSAdmin"])
    body = core.body_json()
    to = core.req_datetime(body, "to_iso8601")
    CLOCK.set(to)
    return ok({"current_utc": fmt(CLOCK.now())})
