"""Reminder routes (PRD §3.12). Quiet-hours + min-gap gates on scheduling."""
from flask import Blueprint, request

import clock
import db
import serialize
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_REMINDER_IN_QUIET_HOURS,
    ERR_REMINDER_TOO_CLOSE,
    ERR_REMINDER_NOT_SCHEDULED,
)
from middleware import require_roles
from response import success, success_list
from services.common import touch, require_string, require_int
from services.lookups import get_session, get_reminder
from services.pagination import paginate

bp = Blueprint("reminders", __name__)

VALID_TARGET_KINDS = {"CONSENT", "QUESTIONNAIRE", "COPAY", "GENERIC"}


def _in_quiet_window(local_min, start, end):
    """Quiet window [start, end) wrapping past midnight (PRD §3.12).

    start inclusive, end exclusive. When start > end the window wraps midnight.
    """
    local_min = local_min % 1440
    if start == end:
        # Degenerate window: no minute is quiet.
        return False
    if start < end:
        return start <= local_min < end
    # Wrap-around: quiet if at/after start OR before end.
    return local_min >= start or local_min < end


@bp.route("/reminders", methods=["POST"])
@require_roles("FrontDeskStaff")
def create_reminder():
    body = request.get_json(silent=True) or {}
    intake_session_id = require_string(body, "intake_session_id")
    target_kind = require_string(body, "target_kind")
    scheduled_raw = require_string(body, "scheduled_utc")
    scheduled_local_min = require_int(body, "scheduled_local_min")
    if target_kind not in VALID_TARGET_KINDS:
        raise err(ERR_INVALID_REQUEST, "invalid target_kind")

    session = get_session(intake_session_id)
    clinic = db.clinics[session["clinic_id"]]
    scheduled_utc = clock.parse_instant(scheduled_raw)

    with db.LOCK:
        # Quiet-hours check (PRD §3.12).
        if _in_quiet_window(scheduled_local_min,
                            clinic["reminder_quiet_start_min"],
                            clinic["reminder_quiet_end_min"]):
            raise err(ERR_REMINDER_IN_QUIET_HOURS, "reminder in quiet hours")

        # Min-gap check: at least reminder_min_gap_minutes from every other
        # non-cancelled reminder on the same session (PRD §3.12).
        gap_minutes = clinic["reminder_min_gap_minutes"]
        for other in db.reminders.values():
            if other["intake_session_id"] != intake_session_id:
                continue
            if other["status"] == "CANCELLED":
                continue
            other_utc = clock.parse_instant(other["scheduled_utc"])
            delta_minutes = abs((scheduled_utc - other_utc).total_seconds()) / 60.0
            if delta_minutes < gap_minutes:
                raise err(ERR_REMINDER_TOO_CLOSE, "reminder too close to another")

        now = db.now_iso()
        reminder = {
            "id": db.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": db.next_seq(),
            "intake_session_id": intake_session_id,
            "target_kind": target_kind,
            "scheduled_utc": clock.format_instant(scheduled_utc),
            "scheduled_local_min": scheduled_local_min,
            "status": "SCHEDULED",
        }
        db.reminders[reminder["id"]] = reminder
    return success(serialize.reminder(reminder), status=201)


@bp.route("/reminders/<rid>", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def get_reminder_route(rid):
    reminder = get_reminder(rid)
    return success(serialize.reminder(reminder), status=200)


@bp.route("/reminders", methods=["GET"])
@require_roles("ClinicAdmin", "FrontDeskStaff", "BillingClerk")
def list_reminders():
    records = list(db.reminders.values())
    val = request.args.get("intake_session_id")
    if val is not None:
        records = [r for r in records if r["intake_session_id"] == val]
    items, limit, offset, total = paginate(records, serialize.reminder)
    return success_list(items, limit, offset, total)


@bp.route("/reminders/<rid>/cancel", methods=["POST"])
@require_roles("FrontDeskStaff")
def cancel_reminder(rid):
    reminder = get_reminder(rid)
    with db.LOCK:
        if reminder["status"] != "SCHEDULED":
            raise err(ERR_REMINDER_NOT_SCHEDULED, "reminder not SCHEDULED")
        reminder["status"] = "CANCELLED"
        touch(reminder)
    return success(serialize.reminder(reminder), status=200)
