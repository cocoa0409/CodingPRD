"""ApprovalRequest endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_APPROVAL_AUTHORITY_EXCEEDED,
)
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.core import touch, cancel_pending_approvals_for
from validate import get_body, opt_str, require_path_resource

bp = Blueprint("approval_requests", __name__)

REQUIRED_ROLE_TO_CALLER = {
    "BUSINESS_MANAGER": "BusinessManager",
    "ARTIST": "Artist",
    "FIRM_ADMIN": "FirmAdmin",
}


@bp.get("/approval-requests/<rid>")
def get_approval_request(rid):
    return get_one("approval_requests", rid)


@bp.get("/approval-requests")
def list_approval_requests():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "target_type": request.args.get("target_type"),
        "target_id": request.args.get("target_id"),
        "required_approver": request.args.get("required_approver"),
        "status": request.args.get("status"),
    }
    return list_response("approval_requests", filters)


def _decide(rid, decision):
    caller = scoped_mutation_auth(["BusinessManager", "Artist", "FirmAdmin"],
                                  "approval_requests", rid)
    body = get_body()
    req = require_path_resource("approval_requests", rid)
    decision_note = opt_str(body, "decision_note")

    # Priority 8: state precondition
    if req["status"] != "PENDING":
        raise_error(ERR_INVALID_STATE, "approval request is not PENDING")
    # Role must match the required approver
    expected_caller_role = REQUIRED_ROLE_TO_CALLER[req["required_approver"]]
    if caller.role != expected_caller_role:
        raise_error(ERR_FORBIDDEN_FOR_ROLE,
                    f"this request requires a {expected_caller_role} decider")
    # Priority 10: segregation of duties
    if caller.user_id == req["requested_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "decider must differ from requester")

    # Priority 14: BUSINESS_MANAGER authority cap on EXPENSE approvals
    if (
        decision == "APPROVED"
        and req["target_type"] == "EXPENSE"
        and req["required_approver"] == "BUSINESS_MANAGER"
    ):
        expense = db["expenses"].get(req["target_id"])
        cap = caller.team_member.get("authority_expense_cap_cents", 100000) if caller.team_member else 0
        if expense is not None and expense["amount_cents"] > cap:
            raise_error(ERR_APPROVAL_AUTHORITY_EXCEEDED,
                        "expense amount exceeds approver authority cap")

    req["status"] = decision
    req["decided_by_user_id"] = caller.user_id
    req["decision_note"] = decision_note
    touch(req)

    if req["target_type"] == "EXPENSE":
        expense = db["expenses"].get(req["target_id"])
        if expense is not None:
            if decision == "REJECTED":
                expense["status"] = "REJECTED"
                expense["rejection_note"] = decision_note
                touch(expense)
                # Sibling PENDING requests -> CANCELLED
                for sib in db["approval_requests"].values():
                    if (
                        sib["target_type"] == "EXPENSE"
                        and sib["target_id"] == expense["id"]
                        and sib["status"] == "PENDING"
                    ):
                        sib["status"] = "CANCELLED"
                        touch(sib)
            else:  # APPROVED
                remaining = [
                    s for s in db["approval_requests"].values()
                    if s["target_type"] == "EXPENSE"
                    and s["target_id"] == expense["id"]
                    and s["status"] == "PENDING"
                ]
                if not remaining:
                    expense["status"] = "APPROVED"
                    touch(expense)
    # OPPORTUNITY targets: approval/rejection does not itself move the opportunity
    return success_object(public(req))


@bp.post("/approval-requests/<rid>/approve")
def approve_request(rid):
    return _decide(rid, "APPROVED")


@bp.post("/approval-requests/<rid>/reject")
def reject_request(rid):
    return _decide(rid, "REJECTED")
