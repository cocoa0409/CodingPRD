"""Logical clock endpoint (AgencyAdmin-only); setting it fires the sweep."""
from flask import Blueprint

from db import CLOCK, now_iso
from middleware import auth, ADMIN
from response import ok
from services import run_delinquency_sweep
from util import as_dt_str, get_body, parse_dt, req

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(ADMIN)
    data = get_body()
    raw = as_dt_str(req(data, "to_iso8601"), "to_iso8601")
    CLOCK["now"] = parse_dt(raw)
    run_delinquency_sweep()
    return ok({"current_utc": now_iso()})
