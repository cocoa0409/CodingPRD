"""The logical unit clock (PRD 2.5): 2 endpoints.

POST /_clock/set_current_utc, GET /_clock
"""

from flask import Blueprint

import clock
import envelope
from const import ALL_ROLES
from fields import s_dt
from pipeline import begin

bp = Blueprint("clock", __name__)


def _view():
    return {"current_utc": clock.fmt_dt(clock.now())}


@bp.post("/_clock/set_current_utc")
def set_clock():
    ctx = begin(roles=ALL_ROLES, specs=[s_dt("current_utc", required=True)])
    # Setting the clock changes no entity state and increments no version.
    clock.CLOCK.set(ctx.v["current_utc"])
    return envelope.obj(_view())


@bp.get("/_clock")
def read_clock():
    begin(roles=ALL_ROLES)
    return envelope.obj(_view())
