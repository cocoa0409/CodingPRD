"""Logical clock endpoint (PRD section 2.4)."""
from flask import Blueprint

from db import CLOCK
from middleware import ADMIN, auth
from response import ok
from util import as_iso_dt, body, required

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(ADMIN)
    data = body()
    to_iso8601 = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
    CLOCK["current"] = to_iso8601
    return ok({"current_utc": CLOCK["current"]})
