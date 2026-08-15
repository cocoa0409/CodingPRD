"""LeaveRequest endpoints (PRD 3.7)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LEAVE_OVERLAP,
    ERR_INSUFFICIENT_LEAVE_BALANCE,
)
from middleware import require_roles, check_employer_ownership, forbid
from response import success_object, success_list
from routes.workers import get_worker_or_404
from services.serializers import serialize_leave_request, serialize_worker
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_date,
    require_int,
    sort_by_created_at,
)

bp = Blueprint("leave_requests", __name__)


def get_leave_or_404(leave_id: str) -> dict:
    lr = db.leave_requests.get(leave_id)
    if lr is None:
        raise_err(ERR_NOT_FOUND, "LeaveRequest id does not exist")
    return lr


def _available_minutes(worker_id: str) -> int:
    return serialize_worker(db.workers[worker_id])["available_leave_minutes"]


@bp.route("/household-payroll/workers/<worker_id>/leave-requests", methods=["POST"])
@require_roles("Worker")
def create_leave_request(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    if _user_id != worker_id:
        forbid("Worker may only request leave for themselves")

    body = get_json_body()
    start_date = require_date(body, "start_date")
    end_date = require_date(body, "end_date")
    if end_date < start_date:
        raise_err(ERR_INVALID_REQUEST, "end_date must be on or after start_date (closed interval)")
    requested_minutes = require_int(body, "requested_minutes")
    if requested_minutes <= 0:
        raise_err(ERR_INVALID_REQUEST, "requested_minutes must be > 0")

    if worker["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Leave create requires an ACTIVE worker")

    # Closed-interval overlap against REQUESTED|APPROVED leaves; back-to-back
    # (other.end + 1 day == start) is allowed by the strict inequality test.
    for other in db.leave_requests.values():
        if other["worker_id"] != worker_id or other["status"] not in ("REQUESTED", "APPROVED"):
            continue
        if start_date <= other["end_date"] and other["start_date"] <= end_date:
            raise_err(ERR_LEAVE_OVERLAP, "Leave interval overlaps an existing REQUESTED|APPROVED leave")

    if requested_minutes > _available_minutes(worker_id):
        raise_err(ERR_INSUFFICIENT_LEAVE_BALANCE, "requested_minutes exceeds available leave balance")

    lr = {
        "worker_id": worker_id,
        "start_date": start_date,
        "end_date": end_date,
        "requested_minutes": requested_minutes,
        "status": "REQUESTED",
    }
    db.stamp_new(lr)
    db.leave_requests[lr["id"]] = lr
    return success_object(serialize_leave_request(lr), 201)


@bp.route("/household-payroll/leave-requests/<leave_id>/approve", methods=["POST"])
@require_roles("HouseholdClient")
def approve_leave(leave_id: str, _user_id: str, _role: str):
    lr = get_leave_or_404(leave_id)
    worker = db.workers.get(lr["worker_id"])
    if worker is not None:
        check_employer_ownership(_user_id, _role, worker["employer_id"])
    if lr["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "Only a REQUESTED leave can be approved")
    if lr["requested_minutes"] > _available_minutes(lr["worker_id"]):
        raise_err(ERR_INSUFFICIENT_LEAVE_BALANCE, "requested_minutes exceeds available leave balance")
    lr["status"] = "APPROVED"
    db.touch(lr)
    return success_object(serialize_leave_request(lr))


@bp.route("/household-payroll/leave-requests/<leave_id>/deny", methods=["POST"])
@require_roles("HouseholdClient")
def deny_leave(leave_id: str, _user_id: str, _role: str):
    lr = get_leave_or_404(leave_id)
    worker = db.workers.get(lr["worker_id"])
    if worker is not None:
        check_employer_ownership(_user_id, _role, worker["employer_id"])
    if lr["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, "Only a REQUESTED leave can be denied")
    lr["status"] = "DENIED"
    db.touch(lr)
    return success_object(serialize_leave_request(lr))


@bp.route("/household-payroll/leave-requests/<leave_id>/cancel", methods=["POST"])
@require_roles("Worker")
def cancel_leave(leave_id: str, _user_id: str, _role: str):
    lr = get_leave_or_404(leave_id)
    if _user_id != lr["worker_id"]:
        forbid("Worker may only cancel their own leave requests")
    if lr["status"] not in ("REQUESTED", "APPROVED"):
        raise_err(ERR_INVALID_STATE, "Only a REQUESTED or APPROVED leave can be cancelled")
    # used_leave_minutes derives from APPROVED requests, so flipping an
    # APPROVED leave to CANCELLED releases the balance automatically.
    lr["status"] = "CANCELLED"
    db.touch(lr)
    return success_object(serialize_leave_request(lr))


@bp.route("/household-payroll/workers/<worker_id>/leave-requests", methods=["GET"])
@require_roles("PayrollAdmin", "HouseholdClient", "Worker")
def list_leave_requests(worker_id: str, _user_id: str, _role: str):
    worker = get_worker_or_404(worker_id)
    if _role == "Worker":
        if _user_id != worker_id:
            forbid("Worker may only list their own leave requests")
    else:
        check_employer_ownership(_user_id, _role, worker["employer_id"])
    limit, offset = parse_pagination()
    items = [lr for lr in db.leave_requests.values() if lr["worker_id"] == worker_id]
    items = sort_by_created_at(items)
    items = apply_filters(items, ["status"])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_leave_request(lr) for lr in page], limit, offset, total)
