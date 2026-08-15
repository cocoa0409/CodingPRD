"""Ops endpoints: logical clock and escalation checkpoint."""

from flask import Blueprint

from db import store, clock
from helpers import body, parse_dt, fmt_dt, serialize_call_ticket, touch
from middleware import get_actor, require_role, require_supervisor_capable
from response import success_object
from services.calculations import ACK_LEVEL_1_MINUTES, ACK_LEVEL_2_MINUTES

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    actor = get_actor()
    require_role(actor, {"PropertyAdmin"})
    data = body()
    to_dt = parse_dt(data.get("to_iso8601"), "to_iso8601")
    clock.set(to_dt)
    return success_object({"now_iso8601": fmt_dt(clock.now())})


@bp.route("/_ops/evaluate-escalations", methods=["POST"])
def evaluate_escalations():
    actor = get_actor()
    require_role(actor, {"PropertyAdmin", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    now = clock.now()
    evaluated = 0
    escalated = []
    tickets = sorted(
        (t for t in store.call_tickets.values() if t["status"] in ("DISPATCHED", "ESCALATED")),
        key=lambda t: (t["created_at"], t["_seq"]),
    )
    for t in tickets:
        if t["dispatched_at"] is None:
            continue
        evaluated += 1
        elapsed_minutes = (now - t["dispatched_at"]).total_seconds() / 60.0
        if t["status"] == "DISPATCHED" and elapsed_minutes > ACK_LEVEL_1_MINUTES:
            # PRD §3.3: DISPATCHED -> ESCALATED at level 1 (only ESCALATED
            # tickets below level 2 advance to level 2).
            t["status"] = "ESCALATED"
            t["escalation_level"] = max(1, t["escalation_level"])
            touch(t)
            escalated.append(serialize_call_ticket(t))
        elif (
            t["status"] == "ESCALATED"
            and t["escalation_level"] < 2
            and elapsed_minutes > ACK_LEVEL_2_MINUTES
        ):
            t["escalation_level"] = 2
            touch(t)
            escalated.append(serialize_call_ticket(t))
    return success_object({"evaluated_count": evaluated, "escalated": escalated})
