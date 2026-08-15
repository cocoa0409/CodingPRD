"""ResearchTask routes."""
import copy

from flask import Blueprint

import db
import services
from db import touch
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_VERSION,
)
from helpers import body, is_int, _MISSING
from middleware import require_roles, require_any_role
from response import success

bp = Blueprint("research_tasks", __name__)


def get_task_or_404(tid):
    t = db.research_tasks.get(tid)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Research task not found")
    return t


def _validate_finding(f):
    if not isinstance(f, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Each finding must be an object")
    kind = f.get("finding_kind")
    if kind not in services.FINDING_KINDS:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "finding_kind must be one of " + ", ".join(services.FINDING_KINDS),
        )
    if not is_int(f.get("amount_cents")):
        raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents is required and must be an integer")
    dac = f.get("daily_accrual_cents")
    if dac is not None and (isinstance(dac, bool) or not isinstance(dac, (int, float))):
        raise ApiError(ERR_INVALID_REQUEST, 400, "daily_accrual_cents must be a number")
    days = f.get("days_outstanding")
    if days is not None and not is_int(days):
        raise ApiError(ERR_INVALID_REQUEST, 400, "days_outstanding must be an integer")
    desc = f.get("description")
    if desc is not None and not isinstance(desc, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "description must be a string")


@bp.get("/research-tasks/<tid>")
def get_research_task(tid):
    require_any_role()
    return success(services.ser_task(get_task_or_404(tid)))


@bp.post("/research-tasks/<tid>/record-findings")
def record_findings(tid):
    require_roles("ResearchAnalyst")
    t = get_task_or_404(tid)
    if t["status"] not in ("PENDING", "IN_PROGRESS", "UNABLE_TO_REACH"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Task in {t['status']} cannot record findings",
        )
    b = body()
    expected = b.get("expected_research_task_version", _MISSING)
    if expected is _MISSING or not is_int(expected):
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "expected_research_task_version is required and must be an integer",
        )
    findings = b.get("findings", _MISSING)
    if findings is _MISSING or not isinstance(findings, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "findings is required and must be an array")
    for f in findings:
        _validate_finding(f)
    if expected != t["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_research_task_version does not match current version")
    if t["status"] == "UNABLE_TO_REACH":
        t["unreachable_reason"] = None
    t["status"] = "IN_PROGRESS"
    t["findings"] = copy.deepcopy(findings)
    t["findings_recorded"] = True
    total, violations = services.task_findings_amounts(t["findings"])
    t["unpaid_balance_cents"] = total
    t["open_violation_count"] = violations
    touch(t)
    return success(services.ser_task(t))


@bp.post("/research-tasks/<tid>/complete")
def complete_task(tid):
    uid = require_roles("ResearchAnalyst")
    t = get_task_or_404(tid)
    if t["status"] != "IN_PROGRESS" or not t["findings_recorded"]:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Task in {t['status']} cannot be completed",
        )
    t["status"] = "COMPLETED"
    t["completed_by_user_id"] = uid
    touch(t)
    order = db.search_orders.get(t["search_order_id"])
    if order is not None:
        touch(order)  # order totals advanced by the completion
    return success(services.ser_task(t))


@bp.post("/research-tasks/<tid>/mark-unreachable")
def mark_unreachable(tid):
    require_roles("ResearchAnalyst")
    t = get_task_or_404(tid)
    if t["status"] not in ("PENDING", "IN_PROGRESS"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, 409,
            f"Task in {t['status']} cannot be marked unreachable",
        )
    b = body()
    reason = b.get("reason")
    if not isinstance(reason, str) or not reason:
        raise ApiError(ERR_INVALID_REQUEST, 400, "reason is required")
    t["status"] = "UNABLE_TO_REACH"
    t["unreachable_reason"] = reason
    touch(t)
    return success(services.ser_task(t))
