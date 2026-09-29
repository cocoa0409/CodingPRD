"""Logical clock control (PRD section 2.5)."""
from flask import Blueprint, request

from authz import ESTATE_ADMIN, authenticate, require_role
from clock import CLOCK, parse_datetime
from response import single
from validation import parse_body, v_datetime, validate

bp = Blueprint("system", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate(request)
    require_role(role, (ESTATE_ADMIN,))
    body = validate(parse_body(request), required={"to_iso8601": v_datetime()})
    CLOCK.set(parse_datetime(body["to_iso8601"]))
    return single({"current_utc": CLOCK.iso()}, 200)
