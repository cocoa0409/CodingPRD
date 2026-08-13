"""Logical clock endpoint (PRD §2.4).

POST /compliance/_clock/set_current_utc — PlatformAdmin only. Setting the
clock is a system-wide recomputation event: plan deadline postures (with
DEADLINE_BREACH escalation spawning), open gap scores, and rollout past_due
are all re-evaluated. Gap scores and past_due are derived on read; posture
is stored and recomputed here.
"""

from flask import Blueprint

from db import fmt_dt, store
from middleware import auth_context, get_body, req_dt, require_roles
from response import success_object
from services.audit import append_audit
from services.cascades import recompute_all_postures

bp = Blueprint("clock", __name__)

ACTION = "POST /compliance/_clock/set_current_utc"


@bp.post("/compliance/_clock/set_current_utc")
def set_current_utc():
    user_id, role = auth_context()
    require_roles(role, ("PlatformAdmin",))
    body = get_body()
    to = req_dt(body, "to_iso8601")

    store.clock = to
    # Posture recompute spawns DEADLINE_BREACH escalations; owner counters and
    # suspension flags are computed on read, gap scores and past_due likewise.
    recompute_all_postures()
    append_audit(user_id, role, ACTION, "LogicalClock", "logical_clock")
    return success_object({"current_utc": fmt_dt(store.clock)})
