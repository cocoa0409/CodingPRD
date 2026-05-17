"""Test-driving endpoints: /_clock /_clock/advance /_sweep/run."""
from __future__ import annotations

from flask import Blueprint

from ..auth import ROLE_LAB_DIRECTOR, ROLE_LAB_TECH, ROLE_ORDERING_PROVIDER, require_roles
from ..clock import clock, iso_format, now
from ..helpers import parse_iso8601, require_json_object
from ..responses import ok
from ..services import calculations as calc
from ..services.audit import write_audit_event
from ..services.lookups import get_lab_order, get_lab_result
from ..services.workflows import bump, issue_retest
from ..store import store

bp = Blueprint("test_infra", __name__)


@bp.route("/_clock", methods=["GET"])
@require_roles(ROLE_ORDERING_PROVIDER, ROLE_LAB_TECH, ROLE_LAB_DIRECTOR)
def get_clock(**_):
    return ok({"now": iso_format(now())})


@bp.route("/_clock/advance", methods=["POST"])
@require_roles(ROLE_LAB_DIRECTOR)
def advance_clock(**_):
    body = require_json_object()
    target = parse_iso8601(body.get("to_iso8601"), "to_iso8601")
    clock.advance_to(target)
    return ok({"now": iso_format(now())})


@bp.route("/_sweep/run", methods=["POST"])
@require_roles(ROLE_LAB_DIRECTOR)
def run_sweep(**_):
    """attempt_escalation per calc §1.3: sweep PENDING/ESCALATED ordered by
    (ack_deadline_at ASC, created_at ASC). Order-sensitive for audit determinism.
    """
    with store().lock:
        eligible = [
            n for n in store().critical_notifications.values()
            if n["status"] in ("PENDING", "ESCALATED")
        ]
        eligible.sort(key=lambda n: (n["ack_deadline_at"], n["created_at"]))

        current = now()
        actions = 0
        for n in eligible:
            if current < n["ack_deadline_at"]:
                continue
            result = get_lab_result(n["lab_result_id"])
            order = get_lab_order(result["lab_order_id"])
            if n["status"] == "PENDING" and n["channel"] == "SMS":
                n["channel"] = "VOICE"
                n["status"] = "ESCALATED"
                n["attempt_count"] += 1
                n["ack_deadline_at"] = calc.ack_deadline_extended(n["ack_deadline_at"])
                bump(n)
                write_audit_event(
                    event_type="CRITICAL_ESCALATED",
                    lab_order_id=order["id"],
                    actor_id="system",
                    payload={
                        "notification_id": n["id"],
                        "from_channel": "SMS",
                        "to_channel": "VOICE",
                    },
                )
                actions += 1
            elif n["status"] == "ESCALATED" and n["channel"] == "VOICE":
                n["status"] = "FAILED"
                n["attempt_count"] += 1
                bump(n)
                issue_retest(order, reason="CRITICAL_UNACKNOWLEDGED")
                write_audit_event(
                    event_type="CRITICAL_ESCALATED",
                    lab_order_id=order["id"],
                    actor_id="system",
                    payload={
                        "notification_id": n["id"],
                        "failure": True,
                    },
                )
                actions += 1
    return ok({"actions_taken": actions})
