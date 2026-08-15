"""Logical clock endpoint (test-driving capability, DispatchAdmin only)."""
from flask import Blueprint

from middleware import auth
from response import ok
from services import set_clock
from util import as_iso_dt, body, reject_unknown, required

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    auth(["DispatchAdmin"])
    data = body()
    reject_unknown(data, {"to_iso8601"})
    to_iso8601 = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
    set_clock(to_iso8601)
    return ok({"current_utc": to_iso8601})
