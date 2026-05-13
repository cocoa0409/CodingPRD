"""DepartmentAssignment lifecycle: accept, reject, reassign, opinion, escalate."""

from flask import g

from errors import (
    AppError, ERR_VALIDATION, ERR_ASSIGNMENT_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
    ERR_ASSIGNMENT_NOT_PENDING, ERR_FORBIDDEN, ERR_JURISDICTION_MISMATCH,
    ERR_INVALID_STATE, ERROR_STATUS,
)
import db
import clock
import validators as V
from services import audit as audit_svc
from services import work_order_calc as calc
from services import work_orders as wo_svc


def find_assignment(wo_id: str, assignment_id: str) -> dict:
    """Existence + parent scope per priority 4 then priority 5."""
    wo_svc.get_work_order(wo_id)  # raises ERR_WORK_ORDER_NOT_FOUND
    a = db.find_by_id("department_assignments", assignment_id)
    if not a or a["work_order_id"] != wo_id:
        raise AppError(ERR_ASSIGNMENT_NOT_FOUND, "Assignment not found",
                       ERROR_STATUS[ERR_ASSIGNMENT_NOT_FOUND])
    return a


def list_assignments(wo_id: str) -> list[dict]:
    wo_svc.get_work_order(wo_id)
    rows = [a for a in db.all_rows("department_assignments") if a["work_order_id"] == wo_id]
    rows.sort(key=lambda a: a["created_at"])
    return rows


def accept(wo_id: str, assignment_id: str) -> dict:
    a = find_assignment(wo_id, assignment_id)
    if a["stage_status"] != "DISPATCHED":
        raise AppError(ERR_ASSIGNMENT_NOT_PENDING, "Assignment not pending",
                       ERROR_STATUS[ERR_ASSIGNMENT_NOT_PENDING])

    # Acting handler check: g.user_id is the Handler.id; must reference handler whose department_id matches.
    handler = db.find_by_id("handlers", g.user_id)
    if not handler:
        raise AppError(ERR_FORBIDDEN, "User is not a known handler", ERROR_STATUS[ERR_FORBIDDEN])
    if handler["department_id"] != a["department_id"]:
        raise AppError(ERR_FORBIDDEN, "Handler department mismatch", ERROR_STATUS[ERR_FORBIDDEN])
    if handler["status"] != "ACTIVE":
        raise AppError(ERR_FORBIDDEN, "Handler not active", ERROR_STATUS[ERR_FORBIDDEN])

    now_iso = clock.now_iso()
    db.update_fields(a, {
        "stage_status": "ACCEPTED",
        "handler_id": handler["id"],
        "accepted_at": now_iso,
    })
    db.update_fields(handler, {
        "open_assignment_count": int(handler.get("open_assignment_count", 0)) + 1,
    })

    # If LEAD and parent in DISPATCHED or REOPENED, parent moves to IN_PROGRESS.
    if a["role"] == "LEAD":
        wo = wo_svc.get_work_order(wo_id)
        if wo["status"] in ("DISPATCHED", "REOPENED"):
            db.update_fields(wo, {"status": "IN_PROGRESS"})

    audit_svc.write_audit("ACCEPT", wo_id, {
        "assignment_id": a["id"], "handler_id": handler["id"], "role": a["role"],
    })
    return a


def reject(wo_id: str, assignment_id: str, body: dict) -> dict:
    a = find_assignment(wo_id, assignment_id)
    if a["stage_status"] != "DISPATCHED":
        raise AppError(ERR_ASSIGNMENT_NOT_PENDING, "Assignment not pending",
                       ERROR_STATUS[ERR_ASSIGNMENT_NOT_PENDING])
    reason = V.is_str(body, "rejection_reason", min_len=1, max_len=500)

    db.update_fields(a, {"stage_status": "REJECTED", "rejection_reason": reason})
    d = db.find_by_id("departments", a["department_id"])
    if d and int(d.get("pending_work_count", 0)) > 0:
        db.update_fields(d, {"pending_work_count": int(d["pending_work_count"]) - 1})
    audit_svc.write_audit("REJECT", wo_id, {
        "assignment_id": a["id"], "rejection_reason": reason, "role": a["role"],
    })
    return a


def reassign(wo_id: str, assignment_id: str, body: dict) -> dict:
    a = find_assignment(wo_id, assignment_id)
    if not (a["stage_status"] == "DISPATCHED" or (a["stage_status"] == "REJECTED" and a["role"] == "LEAD")):
        raise AppError(ERR_ASSIGNMENT_NOT_PENDING,
                       "Reassign requires DISPATCHED or (REJECTED + LEAD)",
                       ERROR_STATUS[ERR_ASSIGNMENT_NOT_PENDING])

    if "target_department_id" not in body or body["target_department_id"] is None:
        raise AppError(ERR_VALIDATION, "target_department_id is required",
                       ERROR_STATUS[ERR_VALIDATION])
    target_id = body["target_department_id"]
    if not isinstance(target_id, str):
        raise AppError(ERR_VALIDATION, "target_department_id must be string",
                       ERROR_STATUS[ERR_VALIDATION])
    target = db.find_by_id("departments", target_id)
    if target is None:
        raise AppError(ERR_REFERENCE_NOT_FOUND, "target_department_id does not resolve",
                       ERROR_STATUS[ERR_REFERENCE_NOT_FOUND])
    if target["status"] != "ACTIVE":
        raise AppError(ERR_REFERENCE_NOT_FOUND, "target department not ACTIVE",
                       ERROR_STATUS[ERR_REFERENCE_NOT_FOUND])

    wo = wo_svc.get_work_order(wo_id)
    if a["role"] == "LEAD":
        # priority 15 jurisdiction mismatch.
        jur_codes = target.get("jurisdiction_codes") or []
        if jur_codes and wo["jurisdiction_code"] not in jur_codes:
            raise AppError(ERR_JURISDICTION_MISMATCH, "Target does not serve jurisdiction",
                           ERROR_STATUS[ERR_JURISDICTION_MISMATCH])

    was_already_decremented = (a["stage_status"] == "REJECTED")
    # Original → REASSIGNED
    db.update_fields(a, {"stage_status": "REASSIGNED"})
    if not was_already_decremented:
        src = db.find_by_id("departments", a["department_id"])
        if src and int(src.get("pending_work_count", 0)) > 0:
            db.update_fields(src, {"pending_work_count": int(src["pending_work_count"]) - 1})

    now_iso = clock.now_iso()
    new_a = db.insert("department_assignments", {
        "work_order_id": wo_id,
        "department_id": target_id,
        "role": a["role"],
        "handler_id": None,
        "stage_status": "DISPATCHED",
        "rejection_reason": None,
        "opinion_text": None,
        "opinion_decision": None,
        "dispatched_at": now_iso,
        "accepted_at": None,
        "opinion_submitted_at": None,
    })
    db.update_fields(target, {"pending_work_count": int(target.get("pending_work_count", 0)) + 1})

    if a["role"] == "LEAD":
        db.update_fields(wo, {"lead_department_id": target_id})

    audit_svc.write_audit("REASSIGN", wo_id, {
        "original_assignment_id": a["id"],
        "new_assignment_id": new_a["id"],
        "target_department_id": target_id,
        "role": a["role"],
    })
    return new_a


def submit_opinion(wo_id: str, assignment_id: str, body: dict) -> dict:
    a = find_assignment(wo_id, assignment_id)
    if a["role"] != "SUPPORTING":
        raise AppError(ERR_ASSIGNMENT_NOT_PENDING, "Only SUPPORTING assignments may submit opinion",
                       ERROR_STATUS[ERR_ASSIGNMENT_NOT_PENDING])
    if a["stage_status"] != "ACCEPTED":
        raise AppError(ERR_ASSIGNMENT_NOT_PENDING, "Opinion requires ACCEPTED",
                       ERROR_STATUS[ERR_ASSIGNMENT_NOT_PENDING])

    opinion_text = V.is_str(body, "opinion_text", min_len=1, max_len=2000)
    opinion_decision = V.is_enum(body, "opinion_decision", {"AGREE", "DISAGREE", "ABSTAIN"})

    handler = db.find_by_id("handlers", a.get("handler_id") or "")
    now_iso = clock.now_iso()
    db.update_fields(a, {
        "stage_status": "OPINION_SUBMITTED",
        "opinion_text": opinion_text,
        "opinion_decision": opinion_decision,
        "opinion_submitted_at": now_iso,
    })
    d = db.find_by_id("departments", a["department_id"])
    if d and int(d.get("pending_work_count", 0)) > 0:
        db.update_fields(d, {"pending_work_count": int(d["pending_work_count"]) - 1})
    if handler and int(handler.get("open_assignment_count", 0)) > 0:
        db.update_fields(handler, {"open_assignment_count": int(handler["open_assignment_count"]) - 1})

    audit_svc.write_audit("OPINION_SUBMIT", wo_id, {
        "assignment_id": a["id"], "opinion_decision": opinion_decision,
    })
    return a


def escalate(wo_id: str, assignment_id: str) -> dict:
    a = find_assignment(wo_id, assignment_id)
    if a["stage_status"] != "ACCEPTED":
        raise AppError(ERR_ASSIGNMENT_NOT_PENDING, "Escalate requires ACCEPTED",
                       ERROR_STATUS[ERR_ASSIGNMENT_NOT_PENDING])

    db.update_fields(a, {"stage_status": "ESCALATED"})

    existing_open = [
        t for t in db.all_rows("supervision_tasks")
        if t["work_order_id"] == wo_id and t["status"] == "OPEN"
    ]
    if existing_open:
        t = existing_open[0]
        new_level = min(3, int(t.get("escalation_level", 0)) + 1)
        db.update_fields(t, {"escalation_level": new_level})
    else:
        t = db.insert("supervision_tasks", {
            "work_order_id": wo_id,
            "reason": "MANUAL",
            "status": "ESCALATED",
            "escalation_level": 1,
            "last_reminder_at": None,
        })

    audit_svc.write_audit("ESCALATE", wo_id, {
        "assignment_id": a["id"], "supervision_task_id": t["id"],
    })
    audit_svc.emit_sync(wo_id, "ESCALATED", {"work_order_id": wo_id})
    return a
