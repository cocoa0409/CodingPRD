"""Adjustment routes: create, get, list, approve, reject."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_ADJUSTMENT_AMOUNT_INVALID,
)
from middleware import authorized, check_rep_ownership
from response import success_object, success_list
from util import new_entity, touch, serialize
from validate import (
    get_body, req_str, req_int,
    parse_pagination, require_path_resource,
)

bp = Blueprint("adjustments", __name__)

ANALYST_ONLY = ["CompAnalyst"]
MANAGER_ONLY = ["CompManager"]
ALL_ROLES = ["CompAdmin", "CompAnalyst", "CompManager", "Rep"]


@bp.route("/adjustments", methods=["POST"])
def create_adjustment():
    caller = authorized(ANALYST_ONLY)
    body = get_body()

    assignment_id = req_str(body, "assignment_id")
    amount_cents = req_int(body, "amount_cents")
    reason = req_str(body, "reason")

    # Priority 3: assignment exists
    assignment = db["assignments"].get(assignment_id)
    if assignment is None:
        raise_error(ERR_NOT_FOUND, f"assignment not found: {assignment_id}")

    # Priority 9: amount nonzero
    if amount_cents == 0:
        raise_error(ERR_ADJUSTMENT_AMOUNT_INVALID,
                    "adjustment amount_cents must be nonzero")

    program = db["programs"][assignment["program_id"]]

    adjustment = new_entity({
        "assignment_id": assignment_id,
        "dispute_id": None,
        "amount_cents": amount_cents,
        "source": "MANUAL",
        "reason": reason,
        "period_index": program["current_period_index"],
        "created_by_user_id": caller.user_id,
        "status": "PENDING_APPROVAL",
    })
    db["adjustments"][adjustment["id"]] = adjustment
    return success_object(serialize(adjustment), 201)


@bp.route("/adjustments/<adjustmentId>", methods=["GET"])
def get_adjustment(adjustmentId):
    caller = authorized(ALL_ROLES)
    adjustment = require_path_resource("adjustments", adjustmentId)
    return success_object(serialize(adjustment))


@bp.route("/adjustments", methods=["GET"])
def list_adjustments():
    caller = authorized(ALL_ROLES)
    limit, offset = parse_pagination()

    items = list(db["adjustments"].values())

    # Filters
    assignment_id = request.args.get("assignment_id")
    dispute_id = request.args.get("dispute_id")
    period_index = request.args.get("period_index")
    status_filter = request.args.get("status")

    if assignment_id:
        items = [a for a in items if a["assignment_id"] == assignment_id]
    if dispute_id:
        items = [a for a in items if a.get("dispute_id") == dispute_id]
    if period_index:
        try:
            pi = int(period_index)
            items = [a for a in items if a["period_index"] == pi]
        except (ValueError, TypeError):
            pass
    if status_filter:
        items = [a for a in items if a["status"] == status_filter]

    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(a) for a in page], total, limit, offset)


@bp.route("/adjustments/<adjustmentId>/approve", methods=["POST"])
def approve_adjustment(adjustmentId):
    caller = authorized(MANAGER_ONLY)
    adjustment = require_path_resource("adjustments", adjustmentId)

    # Priority 4: state — must be PENDING_APPROVAL
    if adjustment["status"] != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"adjustment is {adjustment['status']}, must be PENDING_APPROVAL")

    # Priority 5: segregation of duties
    if caller.user_id == adjustment["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "approver must differ from adjustment creator")

    adjustment["status"] = "APPROVED"
    touch(adjustment)
    return success_object(serialize(adjustment))


@bp.route("/adjustments/<adjustmentId>/reject", methods=["POST"])
def reject_adjustment(adjustmentId):
    caller = authorized(MANAGER_ONLY)
    adjustment = require_path_resource("adjustments", adjustmentId)

    # Priority 4: state — must be PENDING_APPROVAL
    if adjustment["status"] != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"adjustment is {adjustment['status']}, must be PENDING_APPROVAL")

    adjustment["status"] = "REJECTED"
    touch(adjustment)
    return success_object(serialize(adjustment))
