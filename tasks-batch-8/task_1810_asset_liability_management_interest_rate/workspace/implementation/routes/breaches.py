"""LimitBreach endpoints (PRD 3.5): list/get plus the ALCOChair-worked
lifecycle acknowledge -> remediation-plan -> close."""

import store
from envelope import list_response, object_response
from errors import ApiError
from serializers import breach_json
from services import recompute_report_if_exists, touch
from validate import req_instant, req_str

from routes.common import READ_ROLES, endpoint, get_or_404


@endpoint("GET", "/breaches", roles=READ_ROLES)
def list_breaches(ctx):
    rows = list(store.breaches.values())
    for field in ("book_id", "run_id", "limit_id", "metric", "status"):
        value = ctx.args.get(field)
        if value is not None:
            rows = [b for b in rows if b[field] == value]
    return list_response(rows, ctx.args, breach_json)


@endpoint("GET", "/breaches/<breach_id>", roles=READ_ROLES)
def get_breach(ctx):
    breach = get_or_404(store.breaches, ctx.param("breach_id"))
    return object_response(breach_json(breach))


@endpoint("POST", "/breaches/<breach_id>/acknowledge", roles=["ALCOChair"])
def acknowledge_breach(ctx):
    breach = get_or_404(store.breaches, ctx.param("breach_id"))
    # Rung 6: OPEN -> ACKNOWLEDGED, and ESCALATED -> ACKNOWLEDGED.
    if breach["status"] not in ("OPEN", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    breach["status"] = "ACKNOWLEDGED"
    touch(breach)
    recompute_report_if_exists(breach["book_id"], breach["period_month"])
    return object_response(breach_json(breach))


@endpoint("POST", "/breaches/<breach_id>/remediation-plan", roles=["ALCOChair"])
def remediation_plan_breach(ctx):
    breach = get_or_404(store.breaches, ctx.param("breach_id"))
    # Rung 4 (outranks rung 6): non-empty note and a parseable due date.
    note = req_str(ctx.body, "remediation_note")
    due_date = req_instant(ctx.body, "due_date")
    # Rung 6: ACKNOWLEDGED -> REMEDIATION_PLANNED only.
    if breach["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    breach["remediation_note"] = note
    breach["due_date"] = due_date  # caller-supplied instant, echoed verbatim
    breach["status"] = "REMEDIATION_PLANNED"
    touch(breach)
    return object_response(breach_json(breach))


@endpoint("POST", "/breaches/<breach_id>/close", roles=["ALCOChair"])
def close_breach(ctx):
    breach = get_or_404(store.breaches, ctx.param("breach_id"))
    # Rung 4 (outranks rung 6): non-empty resolution note.
    note = req_str(ctx.body, "resolution_note")
    # Rung 6: CLOSED is reachable from ACKNOWLEDGED or REMEDIATION_PLANNED.
    if breach["status"] not in ("ACKNOWLEDGED", "REMEDIATION_PLANNED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    breach["resolution_note"] = note
    breach["status"] = "CLOSED"
    touch(breach)
    recompute_report_if_exists(breach["book_id"], breach["period_month"])
    return object_response(breach_json(breach))
