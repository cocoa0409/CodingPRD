"""The logical clock (PRD 2.5). Moving it mutates no row and bumps no version."""

from flask import Blueprint

import validate as v
from envelope import ok
from store import iso, now_logical, set_clock

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    v.auth(("VenueOperationsDirector",))
    payload = v.body()
    instant = v.req_dt(payload, "to_iso8601")
    set_clock(instant)
    return ok({"current_utc": iso(now_logical())})
