"""Logical clock test-driving endpoint (PRD 2.4)."""
from flask import Blueprint

from db import fmt_dt, now, set_clock
from middleware import auth
from response import ok
from util import body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/pilotage/_clock/set_current_utc")
def set_current_utc():
    auth(["AssociationAdmin"])
    data = body()
    target = req_dt(data, "to_iso8601")
    set_clock(target)
    # Tariff schedule statuses are computed at read time, so advancing the
    # clock re-resolves them automatically; rested-pilot eligibility and the
    # rolling duty window are likewise evaluated against the clock live.
    return ok({"current_utc": fmt_dt(now())})
