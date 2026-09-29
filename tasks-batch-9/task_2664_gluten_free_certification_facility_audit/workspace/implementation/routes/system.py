"""System endpoints: the surveillance sweep and the logical clock setter."""

from flask import Blueprint

import clock
import middleware as mw
import response
from constants import ROLE_PROGRAM_ADMIN
from services import sweep

bp = Blueprint("system", __name__)


@bp.post("/gfco/surveillance-runs")
def surveillance_run():
    mw.authenticate([ROLE_PROGRAM_ADMIN])
    mw.body()
    return response.created(sweep.run())


@bp.post("/gfco/_clock/set_current_utc")
def set_clock():
    mw.authenticate([ROLE_PROGRAM_ADMIN])
    data = mw.body()
    moment = mw.req_dt(data, "to_iso8601")
    clock.CLOCK.set(moment)
    return response.ok({"current_utc": clock.format_iso_instant(clock.now())})
