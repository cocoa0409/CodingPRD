"""Notification endpoints: read, list, and the AidOfficer dispatch sweep.

Dispatch processes QUEUED rows in scheduled_at ascending order at whole-second
precision: obviated APPEAL_DEADLINE_REMINDER rows are cancelled; due rows are
sent. An active appeal (SUBMITTED/UNDER_REVIEW/MORE_INFO_REQUESTED/APPROVED)
or a standing other than SUSPENSION obviates a reminder.
"""

from flask import Blueprint, g, request

import errors
from db import now, store, trunc_second
from middleware import (
    authenticate,
    check_student_ownership,
    paginate,
    pagination_params,
    require_roles,
)
from response import success
from serializers import pub_notification
from services import audit

bp = Blueprint("notifications", __name__)

ANY_ROLE = ("Student", "Registrar", "AidOfficer", "CommitteeMember", "Auditor", "AidAdministrator")
ACTIVE_APPEAL_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED", "APPROVED")


@bp.get("/sap/notifications/<nid>")
def get_notification(nid):
    authenticate()
    require_roles(*ANY_ROLE)
    row = store.notifications.get(nid)
    if row is None:
        errors.fail(errors.ERR_NOT_FOUND, "Notification %s does not exist" % nid)
    check_student_ownership(row["student_id"])
    return success(pub_notification(row))


@bp.get("/sap/notifications")
def list_notifications():
    authenticate()
    require_roles(*ANY_ROLE)
    limit, offset = pagination_params()
    rows = list(store.notifications.values())
    if g.user_role == "Student":
        rows = [n for n in rows if n["student_id"] == g.user_id]
    student_id = request.args.get("student_id")
    if student_id is not None:
        rows = [n for n in rows if n["student_id"] == student_id]
    kind = request.args.get("kind")
    if kind is not None:
        rows = [n for n in rows if n["kind"] == kind]
    status = request.args.get("status")
    if status is not None:
        rows = [n for n in rows if n["status"] == status]
    page, meta = paginate(rows, limit, offset)
    return success([pub_notification(n) for n in page], response_type="array", pagination=meta)


def _reminder_obviated(notification):
    student = store.students.get(notification["student_id"])
    for a in store.appeals.values():
        if (a["student_id"] == notification["student_id"]
                and a["status"] in ACTIVE_APPEAL_STATUSES):
            return True
    return student is None or student["sap_status"] != "SUSPENSION"


@bp.post("/sap/notifications/dispatch")
def dispatch_notifications():
    authenticate()
    require_roles("AidOfficer")
    current = trunc_second(now())
    queued = [n for n in store.notifications.values() if n["status"] == "QUEUED"]
    queued.sort(key=lambda n: (trunc_second(n["scheduled_at"]), n["_seq"]))

    sent_count = 0
    cancelled_count = 0
    for n in queued:
        if n["kind"] == "APPEAL_DEADLINE_REMINDER" and _reminder_obviated(n):
            before = pub_notification(n)
            n["status"] = "CANCELLED"
            n["updated_at"] = now()
            n["version"] += 1
            audit.record("NOTIFICATION_CANCELLED", "Notification", n["id"],
                         n["student_id"], before, pub_notification(n))
            cancelled_count += 1
        elif trunc_second(n["scheduled_at"]) <= current:
            before = pub_notification(n)
            n["status"] = "SENT"
            n["sent_at"] = now()
            n["updated_at"] = now()
            n["version"] += 1
            audit.record("NOTIFICATION_SENT", "Notification", n["id"],
                         n["student_id"], before, pub_notification(n))
            sent_count += 1
    return success({"sent_count": sent_count, "cancelled_count": cancelled_count})
