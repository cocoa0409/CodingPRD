"""Hold audits, reminder logs, disposition freeze windows, sweeps, and the
logical-clock control."""
import math
from decimal import Decimal
from datetime import timedelta

from flask import Blueprint, request

from db import db, new_id, touch, bump, now, set_clock
from errors import err, not_found
from middleware import authenticate, body_json, READ_STAFF
from response import success_object, success_list, paginate
from serializers import audit_view, reminder_log_view, freeze_window_view
from services.core import (
    derive_posture, record_active_hold_count, freeze_window_active,
    create_certificate, destroy_record, add_reminder_log)
from utils import (
    check_str, check_datetime, check_enum, fmt_ts, round_half_up)

bp = Blueprint("misc", __name__)

METHODS = {"SECURE_ERASE", "SHRED", "CRYPTO_SHRED"}


# ---------------------------------------------------------------------------
# Hold Audits
# ---------------------------------------------------------------------------
@bp.route("/ig/hold-audits", methods=["POST"])
def create_audit():
    authenticate(["Auditor"])
    body = body_json()
    program_id = check_str(body, "program_id")
    program = db.programs.get(program_id)
    if program is None:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    t = now()
    # Snapshot: counts over the program at audit creation, frozen thereafter.
    issued_holds = [h for h in db.legal_holds.values()
                    if h["program_id"] == program_id and h["status"] == "ISSUED"]
    stale_cutoff = program["stale_hold_days"] * 86400
    stale_holds = [h for h in issued_holds
                   if h["last_activity_at"] is not None
                   and (t - h["last_activity_at"]).total_seconds() > stale_cutoff]
    live_records = [r for r in db.records.values()
                    if r["program_id"] == program_id and r["status"] == "ACTIVE"]
    held = [r for r in live_records if derive_posture(r) == "HELD"]
    eligible = [r for r in live_records if derive_posture(r) == "ELIGIBLE"]
    over = [r for r in eligible if r["auto_delete_enabled"] is False]
    if len(eligible) == 0:
        pct = 0
    else:
        pct = round_half_up(Decimal(len(over)) * 100 / Decimal(len(eligible)), 2)
        pct = float(pct)
    # Over-preservation cost: round each per-record cost to integer cents
    # FIRST, then sum (sum-then-round is forbidden).
    total_cost = 0
    for r in over:
        days_over = math.floor((t - r["retention_due_date"]).total_seconds() / 86400)
        months_over = days_over // 30
        rclass = db.record_classes.get(r["record_class_id"])
        rate = Decimal(str(rclass["monthly_storage_cost_cents_per_gb"])) \
            if rclass else Decimal(0)
        monthly_cents = Decimal(str(r["size_gb"])) * rate
        per_record = round_half_up(monthly_cents * months_over, 0)
        total_cost += int(per_record)
    a = {
        "id": new_id(),
        "program_id": program_id,
        "active_hold_count": len(issued_holds),
        "stale_hold_count": len(stale_holds),
        "held_record_count": len(held),
        "eligible_record_count": len(eligible),
        "over_preserved_record_count": len(over),
        "over_preservation_pct": pct,
        "over_preservation_cost_cents": total_cost,
        "threshold_breached": Decimal(str(pct)) >= Decimal(
            str(program["over_preservation_warn_pct"])),
        "closed_at": None,
        "status": "OPEN",
    }
    touch(a)
    db.hold_audits[a["id"]] = a
    return success_object(audit_view(a), 201)


@bp.route("/ig/hold-audits", methods=["GET"])
def list_audits():
    authenticate(READ_STAFF)
    items = list(db.hold_audits.values())
    a = request.args
    for f in ("program_id", "status"):
        v = a.get(f)
        if v is not None:
            items = [x for x in items if x.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([audit_view(x) for x in window], limit, offset, total)


@bp.route("/ig/hold-audits/<auditId>", methods=["GET"])
def get_audit(auditId):
    authenticate(READ_STAFF)
    a = db.hold_audits.get(auditId)
    if a is None:
        not_found("Hold audit not found")
    return success_object(audit_view(a))


@bp.route("/ig/hold-audits/<auditId>/close", methods=["POST"])
def close_audit(auditId):
    authenticate(["Auditor"])
    a = db.hold_audits.get(auditId)
    if a is None:
        not_found("Hold audit not found")
    if a["status"] != "OPEN":
        raise err("ERR_AUDIT_NOT_OPEN", 409,
                  "Only an OPEN audit can be closed")
    a["status"] = "CLOSED"
    a["closed_at"] = now()
    bump(a)
    return success_object(audit_view(a))


# ---------------------------------------------------------------------------
# Reminder Log (read-only)
# ---------------------------------------------------------------------------
@bp.route("/ig/reminder-logs", methods=["GET"])
def list_reminder_logs():
    authenticate(READ_STAFF)
    items = list(db.reminder_logs.values())
    a = request.args
    for f in ("program_id", "hold_id", "hold_custodian_id", "custodian_id",
              "kind"):
        v = a.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([reminder_log_view(e) for e in window],
                        limit, offset, total)


@bp.route("/ig/reminder-logs/<logId>", methods=["GET"])
def get_reminder_log(logId):
    authenticate(READ_STAFF)
    e = db.reminder_logs.get(logId)
    if e is None:
        not_found("Reminder log entry not found")
    return success_object(reminder_log_view(e))


# ---------------------------------------------------------------------------
# Disposition Freeze Windows (CLOSED-interval semantics)
# ---------------------------------------------------------------------------
@bp.route("/ig/disposition-freeze-windows", methods=["POST"])
def create_freeze_window():
    authenticate(["PlatformAdmin"])
    body = body_json()
    program_id = check_str(body, "program_id")
    start_at = check_datetime(body, "start_at")
    end_at = check_datetime(body, "end_at")
    reason = check_str(body, "reason")
    if end_at < start_at:
        raise err("ERR_INVALID_DATE_RANGE", 400,
                  "end_at must be on or after start_at")
    if program_id not in db.programs:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    # Overlap under CLOSED-interval semantics: shared boundaries count.
    for w in db.freeze_windows.values():
        if w["program_id"] == program_id and w["status"] == "ACTIVE":
            if start_at <= w["end_at"] and w["start_at"] <= end_at:
                raise err("ERR_FREEZE_WINDOW_OVERLAP", 409,
                          "The new window overlaps an existing ACTIVE freeze "
                          "window")
    w = {"id": new_id(), "program_id": program_id, "start_at": start_at,
         "end_at": end_at, "reason": reason, "cancelled_at": None,
         "status": "ACTIVE"}
    touch(w)
    db.freeze_windows[w["id"]] = w
    return success_object(freeze_window_view(w), 201)


@bp.route("/ig/disposition-freeze-windows", methods=["GET"])
def list_freeze_windows():
    authenticate(READ_STAFF)
    items = list(db.freeze_windows.values())
    a = request.args
    for f in ("program_id", "status"):
        v = a.get(f)
        if v is not None:
            items = [w for w in items if w.get(f) == v]
    window, limit, offset, total = paginate(items, request.args)
    return success_list([freeze_window_view(w) for w in window],
                        limit, offset, total)


@bp.route("/ig/disposition-freeze-windows/<windowId>", methods=["GET"])
def get_freeze_window(windowId):
    authenticate(READ_STAFF)
    w = db.freeze_windows.get(windowId)
    if w is None:
        not_found("Disposition freeze window not found")
    return success_object(freeze_window_view(w))


@bp.route("/ig/disposition-freeze-windows/<windowId>/cancel", methods=["POST"])
def cancel_freeze_window(windowId):
    authenticate(["PlatformAdmin"])
    w = db.freeze_windows.get(windowId)
    if w is None:
        not_found("Disposition freeze window not found")
    if w["status"] != "ACTIVE":
        raise err("ERR_FREEZE_WINDOW_NOT_ACTIVE", 409,
                  "Only an ACTIVE freeze window can be cancelled")
    w["status"] = "CANCELLED"
    w["cancelled_at"] = now()
    bump(w)
    return success_object(freeze_window_view(w))


# ---------------------------------------------------------------------------
# Sweeps
# ---------------------------------------------------------------------------
@bp.route("/ig/sweeps/reminders", methods=["POST"])
def sweep_reminders():
    authenticate(["RecordsManager"])
    body = body_json()
    program_id = check_str(body, "program_id")
    program = db.programs.get(program_id)
    if program is None:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    t = now()
    max_reminders = program["max_reminders_before_escalation"]
    due = [a for a in db.hold_custodians.values()
           if a["program_id"] == program_id
           and a["status"] == "PENDING"
           and a["ack_due_date"] is not None
           and a["ack_due_date"] < t]
    due.sort(key=lambda a: a["created_at"])
    reminders_sent = 0
    escalations_raised = 0
    for a in due:
        hold = db.legal_holds[a["hold_id"]]
        if a["reminder_count"] < max_reminders:
            a["reminder_count"] += 1
            a["last_reminder_at"] = t
            bump(a)
            add_reminder_log(hold, a, "REMINDER", a["reminder_count"])
            reminders_sent += 1
        else:
            a["status"] = "ESCALATED"
            a["escalated_at"] = t
            bump(a)
            add_reminder_log(hold, a, "ESCALATION", a["reminder_count"])
            escalations_raised += 1
    return success_object({"reminders_sent": reminders_sent,
                           "escalations_raised": escalations_raised})


@bp.route("/ig/sweeps/auto-delete", methods=["POST"])
def sweep_auto_delete():
    uid, _ = authenticate(["RecordsManager"])
    body = body_json()
    program_id = check_str(body, "program_id")
    method = check_enum(body, "method", METHODS)
    if program_id not in db.programs:
        raise err("ERR_REFERENCED_ENTITY_NOT_FOUND", 404,
                  "Referenced program does not exist")
    if freeze_window_active(program_id):
        raise err("ERR_DISPOSITION_FREEZE_ACTIVE", 409,
                  "An ACTIVE disposition freeze window covers the current "
                  "time for this program")
    candidates = [r for r in db.records.values()
                  if r["program_id"] == program_id
                  and r["status"] == "ACTIVE"
                  and derive_posture(r) == "ELIGIBLE"
                  and r["auto_delete_enabled"] is True
                  and record_active_hold_count(r) == 0]
    # Processing order: created_at ASC, tie-break title ASC (never id).
    candidates.sort(key=lambda r: (r["created_at"], r["title"]))
    certificate_ids = []
    for rec in candidates:
        destroy_record(rec)
        cert = create_certificate(program_id, None, None, rec, method, uid)
        certificate_ids.append(cert["id"])
    return success_object({"destroyed_count": len(certificate_ids),
                           "certificate_ids": certificate_ids})


# ---------------------------------------------------------------------------
# Logical clock (test-driving capability; mounted outside /ig)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(["PlatformAdmin"])
    body = body_json()
    to = check_datetime(body, "to_iso8601")
    set_clock(to)
    return success_object({"current_utc": fmt_ts(to)})
