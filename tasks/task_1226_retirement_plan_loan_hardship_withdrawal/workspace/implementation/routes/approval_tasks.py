"""Approval task endpoints: read, decide (APPROVE | REJECT | REQUEST_DOCS)."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from services import audit
from services.state import (get_approval_task, get_loan, get_hardship, get_plan,
                            require_plan_active, has_active_suspension)
from services.util import now_iso, today, touch

bp = Blueprint("approval_tasks", __name__)

DECISIONS = ("APPROVE", "REJECT", "REQUEST_DOCS")

# Map X-User-Role header value to the chain's approver_role value
ROLE_TO_APPROVER = {
    "PlanSponsor": "PLAN_SPONSOR",
    "RecordkeeperAdmin": "RECORDKEEPER_ADMIN",
}


def _bad(msg):
    return errors.err(errors.ERR_INVALID_REQUEST, msg, 400)


@bp.route("/approval-tasks/<task_id>", methods=["GET"])
def read_task(task_id):
    require_roles("RecordkeeperAdmin", "PlanSponsor", "Auditor")
    task = get_approval_task(task_id)
    return success_object(task)


@bp.route("/approval-tasks/<task_id>/decide", methods=["POST"])
def decide_task(task_id):
    user_id, role = require_roles("PlanSponsor", "RecordkeeperAdmin")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise _bad("Body must be a JSON object")
    decision = body.get("decision")
    if decision not in DECISIONS:
        raise _bad("decision must be APPROVE, REJECT, or REQUEST_DOCS")

    task = get_approval_task(task_id)
    plan = get_plan(task["plan_id"])

    # REQUEST_DOCS valid only for HARDSHIP subjects (schema-level rejection)
    if decision == "REQUEST_DOCS" and task["subject_type"] != "HARDSHIP":
        raise _bad("REQUEST_DOCS is valid only for HARDSHIP subjects")

    # Role must match the task's approver_role
    required_approver = task["approver_role"]
    if ROLE_TO_APPROVER.get(role) != required_approver:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE,
                         f"Task requires approver role {required_approver}", 403)

    # From-state checks
    if task["status"] in ("APPROVED", "REJECTED", "CANCELLED"):
        raise errors.err(errors.ERR_TASK_ALREADY_DECIDED,
                         f"Task already {task['status']}", 409)
    if task["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE,
                         f"Task is in {task['status']} and cannot be decided", 409)

    # Order check: every lower step_order task on the same subject must be APPROVED
    siblings = [t for t in db.approval_tasks.values()
                if t["subject_type"] == task["subject_type"]
                and t["subject_id"] == task["subject_id"]]
    for sib in siblings:
        if sib["step_order"] < task["step_order"] and sib["status"] == "PENDING":
            raise errors.err(errors.ERR_APPROVAL_OUT_OF_ORDER,
                             "A lower step_order task is still PENDING", 409)

    # Segregation of duties: X-User-ID differs from decided_by of every other
    # decided task on the subject, and from the subject's requesting participant id
    subject_participant_id = None
    if task["subject_type"] == "LOAN":
        subject_participant_id = get_loan(task["subject_id"])["participant_id"]
    else:
        subject_participant_id = get_hardship(task["subject_id"])["participant_id"]
    if user_id == subject_participant_id:
        raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                         "The requesting participant may not decide its own subject's task", 403)
    for sib in siblings:
        if sib["id"] == task["id"]:
            continue
        if sib["status"] in ("APPROVED", "REJECTED") and sib.get("decided_by") == user_id:
            raise errors.err(errors.ERR_SEGREGATION_OF_DUTIES,
                             "Same operator may not decide two steps of one subject", 403)

    # Plan posture gate
    require_plan_active(plan)

    # Final-step-only checks for HARDSHIP APPROVE
    max_step = max(s["step_order"] for s in siblings) if siblings else task["step_order"]
    is_final_step = task["step_order"] == max_step
    if decision == "APPROVE" and is_final_step and task["subject_type"] == "HARDSHIP":
        hr = get_hardship(task["subject_id"])
        participant = db.participants[hr["participant_id"]]
        # Priority 9: substantiation
        if plan["substantiation_standard"] == "FULL_DOCUMENTATION":
            docs = [d for d in db.hardship_documents.values()
                    if d["hardship_request_id"] == hr["id"]]
            if not docs:
                raise errors.err(errors.ERR_SUBSTANTIATION_INCOMPLETE,
                                 "FULL_DOCUMENTATION requires at least one uploaded document", 422)
        else:  # SELF_CERTIFY
            if hr.get("attestation") is not True:
                raise errors.err(errors.ERR_SUBSTANTIATION_INCOMPLETE,
                                 "SELF_CERTIFY requires attestation == true", 422)
        # Priority 10: suspension overlap re-check
        if has_active_suspension(participant["id"], today()):
            raise errors.err(errors.ERR_SUSPENSION_OVERLAP,
                             "An ACTIVE suspension record exists for the participant", 422)
        # Priority 12: docs sum under FULL_DOCUMENTATION
        if plan["substantiation_standard"] == "FULL_DOCUMENTATION":
            docs = [d for d in db.hardship_documents.values()
                    if d["hardship_request_id"] == hr["id"]]
            doc_total = sum(d["amount_cents"] for d in docs)
            if doc_total < hr["amount_cents"]:
                raise errors.err(errors.ERR_HARDSHIP_AMOUNT_EXCEEDS_NEED,
                                 "Uploaded documents do not cover the requested amount", 422)

    # Apply the decision
    today_dt = today()
    task["decided_by"] = user_id
    task["decided_on"] = now_iso()

    if decision == "APPROVE":
        task["status"] = "APPROVED"
        touch(task)
        if is_final_step:
            if task["subject_type"] == "LOAN":
                loan = get_loan(task["subject_id"])
                if loan["lifecycle_status"] == "REQUESTED":
                    loan["lifecycle_status"] = "APPROVED"
                    touch(loan)
                    audit.append(plan["id"], role, user_id, "LOAN_APPROVED",
                                 "Loan", loan["id"], {})
            else:
                hr = get_hardship(task["subject_id"])
                if hr["status"] == "UNDER_REVIEW":
                    hr["status"] = "APPROVED"
                    touch(hr)
                    audit.append(plan["id"], role, user_id, "HARDSHIP_APPROVED",
                                 "HardshipRequest", hr["id"], {})
    elif decision == "REJECT":
        task["status"] = "REJECTED"
        touch(task)
        if task["subject_type"] == "LOAN":
            loan = get_loan(task["subject_id"])
            if loan["lifecycle_status"] == "REQUESTED":
                loan["lifecycle_status"] = "DENIED"
                touch(loan)
        else:
            hr = get_hardship(task["subject_id"])
            if hr["status"] == "UNDER_REVIEW":
                hr["status"] = "DENIED"
                touch(hr)
        for sib in siblings:
            if sib["id"] != task["id"] and sib["status"] == "PENDING":
                sib["status"] = "CANCELLED"
                touch(sib)
    else:  # REQUEST_DOCS
        task["status"] = "DOCS_REQUESTED"
        touch(task)
        hr = get_hardship(task["subject_id"])
        if hr["status"] == "UNDER_REVIEW":
            hr["status"] = "PENDING_DOCUMENTS"
            touch(hr)

    audit.append(plan["id"], role, user_id, "APPROVAL_DECIDED",
                 "ApprovalTask", task["id"],
                 {"decision": decision,
                  "subject_type": task["subject_type"],
                  "subject_id": task["subject_id"]})
    return success_object(task)
