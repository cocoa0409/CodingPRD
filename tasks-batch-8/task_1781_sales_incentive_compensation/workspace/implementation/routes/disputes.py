"""Dispute routes: create, get, list, start-review, approve, reject, withdraw."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_DISPUTE_WINDOW_CLOSED,
    ERR_DISPUTE_ALREADY_ACTIVE,
    ERR_DISPUTE_CREDIT_ENTRY_MISMATCH,
    ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT,
)
from middleware import authorized, check_rep_ownership
from response import success_object, success_list
from util import new_entity, new_id, now_ts, touch, serialize
from validate import (
    get_body, req_str, opt_str, req_int, req_enum,
    opt_nullable_str, parse_pagination, require_path_resource,
)

bp = Blueprint("disputes", __name__)

REP_ONLY = ["Rep"]
MANAGER_ONLY = ["CompManager"]
ALL_ROLES = ["CompAdmin", "CompAnalyst", "CompManager", "Rep"]

DISPUTE_REASONS = {
    "CREDIT_MISSING", "CREDIT_AMOUNT", "QUOTA_ERROR",
    "CURVE_MISAPPLIED", "DRAW_ERROR", "OTHER",
}


@bp.route("/disputes", methods=["POST"])
def create_dispute():
    caller = authorized(REP_ONLY)
    body = get_body()

    assignment_id = req_str(body, "assignment_id")
    period_index = req_int(body, "period_index")
    reason = req_enum(body, "reason", DISPUTE_REASONS)
    requested_amount_cents = req_int(body, "requested_amount_cents")
    credit_entry_id = opt_nullable_str(body, "credit_entry_id", None)

    # Priority 3: assignment exists + ownership
    assignment = db["assignments"].get(assignment_id)
    if assignment is None:
        raise_error(ERR_NOT_FOUND, f"assignment not found: {assignment_id}")
    check_rep_ownership(caller, assignment["rep_id"])

    program = db["programs"][assignment["program_id"]]

    # Priority 6: dispute filing window
    current = program["current_period_index"]
    if period_index < current - 2 or period_index > current:
        raise_error(ERR_DISPUTE_WINDOW_CLOSED,
                    f"period_index {period_index} outside [{current - 2}, {current}]")

    # Priority 7: single active dispute per (assignment, period)
    for d in db["disputes"].values():
        if (d["assignment_id"] == assignment_id
                and d["period_index"] == period_index
                and d["status"] in ("SUBMITTED", "UNDER_REVIEW")):
            raise_error(ERR_DISPUTE_ALREADY_ACTIVE,
                        "an active dispute already exists for this assignment and period")

    # Priority 8: credit_entry belongs to this assignment
    if credit_entry_id is not None:
        entry = db["credit_entries"].get(credit_entry_id)
        if entry is None:
            raise_error(ERR_NOT_FOUND, f"credit entry not found: {credit_entry_id}")
        if entry["assignment_id"] != assignment_id:
            raise_error(ERR_DISPUTE_CREDIT_ENTRY_MISMATCH,
                        "credit_entry_id belongs to a different assignment")

    # Priority 9: 0 < requested <= credited_for_period
    credited = sum(
        c["credit_amount_cents"]
        for c in db["credit_entries"].values()
        if c["assignment_id"] == assignment_id
        and c["status"] in ("POSTED", "LOCKED")
        and c["posted_period_index"] == period_index
    )
    if requested_amount_cents <= 0 or requested_amount_cents > credited:
        raise_error(ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT,
                    f"requested_amount_cents {requested_amount_cents} exceeds credited {credited} for period {period_index}")

    dispute = new_entity({
        "assignment_id": assignment_id,
        "credit_entry_id": credit_entry_id,
        "period_index": period_index,
        "reason": reason,
        "requested_amount_cents": requested_amount_cents,
        "approved_amount_cents": None,
        "status": "SUBMITTED",
    })
    db["disputes"][dispute["id"]] = dispute
    return success_object(serialize(dispute), 201)


@bp.route("/disputes/<disputeId>", methods=["GET"])
def get_dispute(disputeId):
    caller = authorized(ALL_ROLES)
    dispute = require_path_resource("disputes", disputeId)
    # Rep callers: own disputes only (via assignment)
    if caller.role == "Rep":
        assignment = db["assignments"].get(dispute["assignment_id"])
        if assignment is None:
            raise_error(ERR_NOT_FOUND, "resource not found")
        check_rep_ownership(caller, assignment["rep_id"])
    return success_object(serialize(dispute))


@bp.route("/disputes", methods=["GET"])
def list_disputes():
    caller = authorized(ALL_ROLES)
    limit, offset = parse_pagination()

    items = list(db["disputes"].values())

    # Rep callers: own disputes only (via assignment)
    if caller.role == "Rep":
        own_assignment_ids = {
            a["id"] for a in db["assignments"].values()
            if a["rep_id"] == caller.user_id
        }
        items = [d for d in items if d["assignment_id"] in own_assignment_ids]

    # Filters
    assignment_id = request.args.get("assignment_id")
    credit_entry_id = request.args.get("credit_entry_id")
    status_filter = request.args.get("status")

    if assignment_id:
        items = [d for d in items if d["assignment_id"] == assignment_id]
    if credit_entry_id:
        items = [d for d in items if d.get("credit_entry_id") == credit_entry_id]
    if status_filter:
        items = [d for d in items if d["status"] == status_filter]

    items.sort(key=lambda d: (d["created_at"], d["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(d) for d in page], total, limit, offset)


@bp.route("/disputes/<disputeId>/start-review", methods=["POST"])
def start_review_dispute(disputeId):
    caller = authorized(MANAGER_ONLY)
    dispute = require_path_resource("disputes", disputeId)

    if dispute["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"dispute is {dispute['status']}, must be SUBMITTED")

    dispute["status"] = "UNDER_REVIEW"
    touch(dispute)
    return success_object(serialize(dispute))


@bp.route("/disputes/<disputeId>/approve", methods=["POST"])
def approve_dispute(disputeId):
    caller = authorized(MANAGER_ONLY)
    body = get_body()
    dispute = require_path_resource("disputes", disputeId)

    # Priority 4: state — must be UNDER_REVIEW
    if dispute["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"dispute is {dispute['status']}, must be UNDER_REVIEW")

    # Priority 9: approved amount
    approved_amount_cents = req_int(body, "approved_amount_cents")
    if approved_amount_cents <= 0 or approved_amount_cents > dispute["requested_amount_cents"]:
        raise_error(ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT,
                    f"approved_amount_cents {approved_amount_cents} must be > 0 and <= requested {dispute['requested_amount_cents']}")

    # Side effects
    dispute["approved_amount_cents"] = approved_amount_cents
    dispute["status"] = "APPROVED"
    touch(dispute)

    # Create DISPUTE adjustment
    assignment = db["assignments"][dispute["assignment_id"]]
    program = db["programs"][assignment["program_id"]]
    ts = now_ts()
    adjustment = {
        "id": new_id(),
        "assignment_id": dispute["assignment_id"],
        "dispute_id": dispute["id"],
        "amount_cents": approved_amount_cents,
        "source": "DISPUTE",
        "reason": f"Dispute {dispute['id']} approved",
        "period_index": program["current_period_index"],
        "created_by_user_id": caller.user_id,
        "status": "APPROVED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db["adjustments"][adjustment["id"]] = adjustment

    return success_object(serialize(dispute))


@bp.route("/disputes/<disputeId>/reject", methods=["POST"])
def reject_dispute(disputeId):
    caller = authorized(MANAGER_ONLY)
    dispute = require_path_resource("disputes", disputeId)

    if dispute["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"dispute is {dispute['status']}, must be SUBMITTED or UNDER_REVIEW")

    dispute["status"] = "REJECTED"
    touch(dispute)
    return success_object(serialize(dispute))


@bp.route("/disputes/<disputeId>/withdraw", methods=["POST"])
def withdraw_dispute(disputeId):
    caller = authorized(REP_ONLY)
    dispute = require_path_resource("disputes", disputeId)

    # Ownership check
    assignment = db["assignments"].get(dispute["assignment_id"])
    if assignment is None:
        raise_error(ERR_NOT_FOUND, "resource not found")
    check_rep_ownership(caller, assignment["rep_id"])

    if dispute["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"dispute is {dispute['status']}, must be SUBMITTED or UNDER_REVIEW")

    dispute["status"] = "WITHDRAWN"
    touch(dispute)
    return success_object(serialize(dispute))
