"""The logical harvest clock (PRD 2.6)."""
from flask import Blueprint

import cascades
import validation as v
from authz import ALL_ROLES, auth
from common import CLOCK, iso_clock, read_body, respond

bp = Blueprint("clock", __name__)


@bp.get("/_clock/current_utc")
def get_clock():
    auth(*ALL_ROLES)
    return respond({"current_utc": iso_clock(CLOCK.now)})


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(*ALL_ROLES)
    body = read_body()
    target = v.req_dt(body, "current_utc")
    cascades.advance_clock(target)
    return respond({"current_utc": iso_clock(CLOCK.now)})
