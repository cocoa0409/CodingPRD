"""Operator sweep and the logical clock — PRD 3.9 and 2.4."""

from flask import Blueprint

import services
from auth import authenticate
from clock import CLOCK, fmt_ts
from errors import fail
from response import ok
from validate import body_object, req_ts

bp = Blueprint("ops", __name__)


@bp.post("/regulatory-sweeps")
def regulatory_sweep():
    authenticate(["PlatformAdmin"])
    body_object()
    return ok(services.run_sweep())


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(["PlatformAdmin"])
    body = body_object()
    requested = req_ts(body, "current_utc")

    # Ladder rule 51: the logical clock never moves backwards.
    if requested < CLOCK.now():
        fail("ERR_CLOCK_NOT_MONOTONIC",
             "The logical clock may not be moved backwards.")

    previous = CLOCK.set(requested)
    # Setting the clock applies no time-driven transition of its own.
    return ok({"current_utc": fmt_ts(requested), "previous_utc": fmt_ts(previous)})
