"""Operational endpoints: the logical clock and the escalation sweep."""
from flask import Blueprint

from db import db
from errors import ApiError
from middleware import (ROLE_COORDINATOR, ROLE_OFFICER, ROLE_REGISTRAR,
                        authenticate)
from response import ok
from services.sla import run_escalation_sweep
from util import as_dt, json_body, require

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate([ROLE_COORDINATOR, ROLE_REGISTRAR, ROLE_OFFICER])
    body = json_body()
    raw, parsed = as_dt(require(body, "current_utc"), "current_utc")
    # rung 30c: the clock never moves backwards; standing still is permitted
    if parsed < db.clock:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    previous_raw = db.clock_raw
    db.clock = parsed
    db.clock_raw = raw
    return ok({"current_utc": raw, "previous_utc": previous_raw})


@bp.post("/_sla/run-escalation-sweep")
def run_sweep():
    authenticate([ROLE_COORDINATOR])
    return ok(run_escalation_sweep())
