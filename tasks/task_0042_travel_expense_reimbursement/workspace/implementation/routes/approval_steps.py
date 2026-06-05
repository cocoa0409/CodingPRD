"""ApprovalStep routes: create, get, list, decision (ascending step_order)."""
from flask import Blueprint, request, g

from common import (get_json_body, require_fields, require_string,
                    require_nonneg_int, require_enum, paginate, list_response)
from db import store, base_fields, touch
from errors import err
from middleware import require_roles
from response import success
from services import get_or_404

bp = Blueprint("approval_steps", __name__)


def _step_view(s):
    return dict(s)


@bp.route("/approval-steps", methods=["POST"])
@require_roles("FinanceAdmin")
def create_step():
    body = get_json_body()
    require_fields(body, ["report_id", "approver_id", "step_order"])
    report_id = require_string(body, "report_id")
    approver_id = require_string(body, "approver_id")
    # FK existence left-to-right: report_id then approver_id
    get_or_404(store.expense_reports, report_id)
    get_or_404(store.approvers, approver_id)
    step_order = require_nonneg_int(body, "step_order")
    s = base_fields()
    s.update({
        "report_id": report_id,
        "approver_id": approver_id,
        "step_order": step_order,
        "decision": "PENDING",
        "comment": None,
    })
    store.approval_steps[s["id"]] = s
    return success(_step_view(s), status=201)


@bp.route("/approval-steps/<step_id>", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def get_step(step_id):
    s = get_or_404(store.approval_steps, step_id)
    return success(_step_view(s))


@bp.route("/approval-steps", methods=["GET"])
@require_roles("FinanceAdmin", "Traveler", "Approver")
def list_steps():
    limit, offset = paginate()
    items = list(store.approval_steps.values())
    report_id = request.args.get("report_id")
    approver_id = request.args.get("approver_id")
    if report_id is not None:
        items = [s for s in items if s["report_id"] == report_id]
    if approver_id is not None:
        items = [s for s in items if s["approver_id"] == approver_id]
    page, pagination = list_response(items, limit, offset)
    return success([_step_view(s) for s in page], pagination=pagination)


@bp.route("/approval-steps/<step_id>/decision", methods=["POST"])
@require_roles("Approver")
def decide_step(step_id):
    s = get_or_404(store.approval_steps, step_id)
    # ownership: acting approver is this step's approver_id
    if s["approver_id"] != g.user_id:
        raise err("ERR_NOT_OWNER", "Approver is not assigned to this step")
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = require_enum(body, "decision", {"APPROVE", "REJECT"})
    comment = body.get("comment")
    if comment is not None and not isinstance(comment, str):
        raise err("ERR_INVALID_REQUEST", "comment must be a string")
    # state: step must be PENDING
    if s["decision"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Step is not PENDING")
    # ascending step_order: all earlier steps for same report must be APPROVED
    for other in store.approval_steps.values():
        if other["report_id"] != s["report_id"]:
            continue
        if other["step_order"] < s["step_order"] and other["decision"] != "APPROVED":
            raise err("ERR_OOP_STEP_OUT_OF_ORDER", "Earlier approval step is not APPROVED")
    s["decision"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    if comment is not None:
        s["comment"] = comment
    touch(s)
    return success(_step_view(s))
