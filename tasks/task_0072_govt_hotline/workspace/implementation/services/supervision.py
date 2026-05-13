"""Supervision tasks: ack and close."""

from errors import (
    AppError, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE, ERROR_STATUS,
)
import db
import clock
from services import audit as audit_svc


def list_supervision(limit: int, offset: int, status=None, reason=None) -> tuple[list[dict], int]:
    rows = list(db.all_rows("supervision_tasks"))
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reason is not None:
        rows = [r for r in rows if r["reason"] == reason]
    rows = sorted(rows, key=lambda r: r["created_at"])
    return rows[offset: offset + limit], len(rows)


def get_task(task_id: str) -> dict:
    t = db.find_by_id("supervision_tasks", task_id)
    if not t:
        raise AppError(ERR_RESOURCE_NOT_FOUND, "Supervision task not found",
                       ERROR_STATUS[ERR_RESOURCE_NOT_FOUND])
    return t


def ack(task_id: str) -> dict:
    t = get_task(task_id)
    if t["status"] != "OPEN":
        raise AppError(ERR_INVALID_STATE, "Ack requires OPEN", ERROR_STATUS[ERR_INVALID_STATE])
    db.update_fields(t, {"status": "ACKNOWLEDGED", "last_reminder_at": clock.now_iso()})
    audit_svc.write_audit("SUPERVISION_ACK", t["work_order_id"], {"supervision_task_id": t["id"]})
    return t


def close_task(task_id: str) -> dict:
    t = get_task(task_id)
    if t["status"] not in ("OPEN", "ACKNOWLEDGED", "ESCALATED"):
        raise AppError(ERR_INVALID_STATE, "Task not in closable state",
                       ERROR_STATUS[ERR_INVALID_STATE])
    wo = db.find_by_id("work_orders", t["work_order_id"])
    if not wo or wo["status"] not in ("RESOLVED", "FOLLOWED_UP", "CLOSED"):
        raise AppError(ERR_INVALID_STATE, "Parent work order not yet resolved/closed",
                       ERROR_STATUS[ERR_INVALID_STATE])
    db.update_fields(t, {"status": "CLOSED"})
    return t
