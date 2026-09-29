"""The deterministic logical clock (PRD 2.5)."""

from flask import Blueprint

from common import ROLE_NAMES, body, endpoint
from db import db, iso
from response import ok

bp = Blueprint("misc", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(roles=["SystemAdmin"])
def set_clock():
    payload = body()
    moment = payload.datetime("current_utc")
    db.clock = moment
    return ok({"current_utc": iso(db.clock)})


@bp.get("/_clock")
@endpoint(roles=list(ROLE_NAMES))
def read_clock():
    return ok({"current_utc": iso(db.clock)})
