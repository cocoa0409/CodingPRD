"""The logical clock control endpoint (PRD 2.5). Not mounted under the
/redistricting prefix."""

from flask import Blueprint

from core import (
    ALL_ROLES,
    authenticate,
    body_json,
    db,
    iso3,
    need,
    parse_dt,
    respond,
)

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(ALL_ROLES)
    body = body_json()
    new_instant = parse_dt(need(body, "current_utc"))
    previous = db.clock
    db.clock = new_instant
    return respond({
        "current_utc": iso3(new_instant),
        "previous_utc": iso3(previous),
    })
