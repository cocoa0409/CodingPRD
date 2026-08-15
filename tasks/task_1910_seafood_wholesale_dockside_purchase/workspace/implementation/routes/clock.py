"""Logical clock admin endpoint (PRD section 2.6)."""
from flask import Blueprint

from db import store
from middleware import auth, require
from response import ok
from services.cascades import run_clock_sweeps
from util import body, req_instant, parse_instant

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = auth()
    require(role, {"OperationsManager"})
    b = body()
    raw = req_instant(b, "to_iso8601")
    store.clock = parse_instant(raw)
    # Advancing the clock fires the quote-expiry and lot-expiry sweeps.
    run_clock_sweeps()
    return ok({"current_utc": raw})
