"""System endpoints: logical clock and scheduler epoch (GardenAdmin only)."""
from flask import Blueprint

import clock
import services
from middleware import require_auth, require_role
from response import ok
from util import fmt_ts, parse_dt, require_field
from app_util import body

bp = Blueprint("system", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    data = body()
    to_iso8601 = require_field(data, "to_iso8601")
    dt = parse_dt(to_iso8601, "to_iso8601")
    clock.set_current(dt)
    return ok({"current_utc": fmt_ts(clock.now())})


@bp.post("/api/_scheduler/run_epoch")
def run_epoch():
    ctx = require_auth()
    require_role(ctx, ["GardenAdmin"])
    counts = services.run_epoch()
    return ok({"transitioned_counts": counts})
