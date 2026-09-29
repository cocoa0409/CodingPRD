"""The logical UTC clock every deadline, window and ageing rule reads."""

from flask import Blueprint

import guards
from envelope import ok
from store import db

bp = Blueprint("clock", __name__)


@bp.post("/plan/_clock/set_current_utc")
def set_current_utc():
    guards.authenticate(("PlanAdministrator",))
    data = guards.body()
    current_utc = guards.req_dt(data, "current_utc")
    # No entity row is mutated: every clock-dependent derivation is read-time.
    db.clock = current_utc
    return ok({})
