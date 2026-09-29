"""The logical-clock driver endpoint. Advancing the clock is the only way a policy expires."""
from flask import Blueprint

import recompute
from db import store
from middleware import authenticate, body, get_dt
from response import ok

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate("Underwriter", "UnderwritingManager", "RiskEngineer", "ClaimAdjuster")
    payload = body()
    current_utc = get_dt(payload, "current_utc")
    store.clock = current_utc
    counters = recompute.run_expiry_sweep()
    data = {"current_utc": store.clock}
    data.update(counters)
    return ok(data)
