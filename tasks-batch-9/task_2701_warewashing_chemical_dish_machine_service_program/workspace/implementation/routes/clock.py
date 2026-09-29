"""The logical clock and its deterministic sweep (PRD 2.4)."""

from flask import Blueprint, request

import db
import middleware
import response
from errors import ApiError
from services import derive
from util import days_until, midnight, parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    # The clock hook needs no headers at all; a declared role must still be
    # one the endpoint accepts.
    role = request.headers.get("X-User-Role")
    if role is not None and role.strip():
        if role != middleware.ROLE_PLATFORM_ADMIN:
            raise ApiError(
                "ERR_FORBIDDEN_ROLE",
                "Role %s may not drive the logical clock" % role,
            )
    body = middleware.body_object()
    if "current_utc" not in body or body["current_utc"] is None:
        middleware.bad("current_utc is required")
    raw = body["current_utc"]
    instant = parse_dt(raw)
    if instant is None:
        middleware.bad("current_utc must be an ISO 8601 UTC timestamp")
    if instant < db.db.clock:
        raise ApiError(
            "ERR_INVALID_REQUEST", "The logical clock never runs backwards"
        )

    db.db.clock = instant
    db.db.clock_str = raw.strip()
    counters = run_sweep(instant)
    data = {"current_utc": db.db.clock_str}
    data.update(counters)
    return response.ok(response.payload(data))


def run_sweep(instant):
    moved = 0
    expired = 0
    escalated = 0

    for agreement in db.rows("service_agreements"):
        status = agreement["status"]
        if status not in ("ACTIVE", "RENEWAL_PENDING"):
            continue
        end_date = agreement["term_end_date"]
        if end_date is None:
            continue
        end_instant = midnight(end_date)
        if instant >= end_instant:
            agreement["status"] = "EXPIRED"
            db.mark(agreement)
            derive.cascade_alpha(agreement, retrieval_due_days=30)
            expired += 1
            continue
        if status != "ACTIVE":
            continue
        if days_until(end_date, instant) <= agreement["renewal_notice_days"]:
            agreement["status"] = "RENEWAL_PENDING"
            db.mark(agreement)
            moved += 1

    for ticket in db.rows("service_tickets"):
        if ticket["status"] not in ("QUEUED", "DISPATCHED", "ON_SITE"):
            continue
        if ticket["sla_breached"]:
            continue
        if ticket["response_deadline_at"] >= instant:
            continue
        ticket["sla_breached"] = True
        ticket["escalation_level"] = ticket["escalation_level"] + 1
        db.mark(ticket)
        escalated += 1

    return {
        "agreements_moved_to_renewal_pending": moved,
        "agreements_expired": expired,
        "tickets_escalated": escalated,
    }
