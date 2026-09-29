"""Test-driving surface: the logical clock (PRD §2.4)."""

from flask import Blueprint

from db import iso, now, set_now
from middleware import OPERATOR_ROLES, authenticate
from response import object_response
from validation import Body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(OPERATOR_ROLES)
    body = Body()
    to_iso8601 = body.instant("to_iso8601", required=True)
    set_now(to_iso8601)
    return object_response({"current_utc": iso(now())})
