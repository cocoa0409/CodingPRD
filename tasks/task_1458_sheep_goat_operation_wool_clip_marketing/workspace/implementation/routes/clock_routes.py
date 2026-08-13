"""Logical clock endpoint (PRD 2.5). PlatformAdmin only."""
from flask import Blueprint

import clock
import util
import validate as v
from middleware import require_roles
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    b = v.body()
    target = util.parse_dt(b.get("to_iso8601"), field="to_iso8601")
    current = clock.set_to(target)
    return success({"current_utc": util.ts_domain(current)})
