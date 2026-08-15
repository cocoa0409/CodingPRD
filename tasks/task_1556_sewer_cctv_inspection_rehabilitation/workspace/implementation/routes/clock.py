"""Logical clock test-driving endpoint."""
from flask import Blueprint

import db
from middleware import get_actor, require_roles
from response import success_object
from errors import err_invalid_request
from services.common import body, parse_datetime_field, sweep_notice_expiry

bp = Blueprint("clock", __name__)


@bp.post("/sewer/_clock/set_current_utc")
def set_clock():
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    payload = body()
    target = parse_datetime_field(payload, "to_iso8601", required=True)
    db.clock.set(db._format_iso(target))
    # expiry sweep across every district
    sweep_notice_expiry()
    return success_object({"current_utc": db.now_iso()})
