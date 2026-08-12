"""Logical clock test-driving endpoint."""
from flask import Blueprint, request

import db
from errors import invalid_request
from middleware import require_roles
from response import ok_object
from utils import fmt_dt, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles(["AgencyAdmin"])
    body = request.get_json(silent=True) or {}
    target = parse_dt(body.get("to_iso8601"))
    if target is None:
        invalid_request("to_iso8601 must be an ISO-8601 datetime")
    db.set_now(target)
    return ok_object({"current_utc": fmt_dt(db.now())})
