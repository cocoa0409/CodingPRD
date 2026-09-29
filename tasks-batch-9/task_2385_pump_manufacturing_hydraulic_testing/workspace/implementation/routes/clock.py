"""The server-managed logical clock (PRD section 2.4)."""

from flask import Blueprint

from db import db, iso_business
from middleware import ALL_ROLES, authorize
from response import object_response
from validation import check_keys, get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize("PlatformAdmin")
    body = get_body()
    check_keys(body, ("to_iso8601",))
    instant = req_datetime(body, "to_iso8601")
    db.clock = instant
    return object_response({"current_utc": iso_business(db.clock)})


@bp.get("/_clock")
def read_clock():
    authorize(*ALL_ROLES)
    return object_response({"current_utc": iso_business(db.clock)})
