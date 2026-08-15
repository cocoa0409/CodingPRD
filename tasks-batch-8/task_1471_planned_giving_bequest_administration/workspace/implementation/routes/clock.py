"""POST /giving/_clock/set_current_utc — logical clock + sweeps (PRD 2.4)."""
from flask import Blueprint

import store
from domain import sweep_milestones, sweep_payments
from envelope import success
from security import ALL_ROLES, require_roles
from validate import get_body, parse_dt, validate_body

bp = Blueprint("clock", __name__)


@bp.post("/giving/_clock/set_current_utc")
@require_roles(*ALL_ROLES)
def set_current_utc():
    body = get_body()
    validate_body(body, {"to_iso8601": ("datetime", True, None)})
    target = parse_dt(body["to_iso8601"])
    store.set_clock(target)
    # sweeps applied atomically with the clock write
    sweep_payments()
    sweep_milestones()
    return success({"current_utc": store.iso(target)}, 200)
