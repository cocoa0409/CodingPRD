"""Test-support surface: the logical clock and the nightly program run."""

from flask import Blueprint

import engine
from core import F, authenticate, ok_raw, validate
from store import set_clock, store

bp = Blueprint("admin", __name__)

ADMIN = ["ProgramAdministrator"]

CLOCK_FIELDS = [F("current_utc", "ts")]


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    ctx = authenticate(ADMIN)
    data = validate(ctx.body, CLOCK_FIELDS)
    set_clock(data["current_utc"])
    # Moving the clock recomputes no stored state; derived posture and window
    # counts are refreshed without touching any revision counter.
    for site in list(store.alarm_sites.values()):
        engine.rollup_site(site, bump=False)
    return ok_raw(None)


@bp.post("/_program-runs/nightly")
def run_nightly():
    authenticate(ADMIN)
    engine.nightly_run()
    return ok_raw(None)
