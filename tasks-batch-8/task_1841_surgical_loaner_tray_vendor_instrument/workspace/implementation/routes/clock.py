"""Logical clock route: POST /vendor-office/_clock/set_current_utc."""

from flask import Blueprint

import db
from errors import raise_err
from middleware import get_auth, require_role, get_body
from response import success_object
from services import clock as clock_service

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = get_auth()
    body = get_body(required=True)
    require_role(role, ["VendorCoordinator"])

    new_now = db.parse_dt(body.get("to_iso8601"))
    if new_now is None:
        raise_err("ERR_VALIDATION", "to_iso8601 must be a valid ISO 8601 datetime")

    db.set_clock(new_now)
    clock_service.sweep(new_now)

    return success_object({"current_utc": db.fmt_ts(new_now)})
