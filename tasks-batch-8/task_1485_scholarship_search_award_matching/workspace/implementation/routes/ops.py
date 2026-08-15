"""Logical clock + daily operations run (PRD §2.6)."""

from flask import Blueprint

import clock
import db
from errors import raise_err
from middleware import require_roles, body
from response import success
from services import engine

bp = Blueprint("ops", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock():
    data = body()
    to_iso8601 = data.get("to_iso8601")
    if not isinstance(to_iso8601, str) or not to_iso8601:
        raise_err("ERR_VALIDATION", "to_iso8601 is required")
    try:
        clock.set_clock(to_iso8601)
    except ValueError:
        raise_err("ERR_VALIDATION", "to_iso8601 is not a valid ISO8601 instant")
    return success({"now": clock.now_echo()})


@bp.route("/api/_ops/run_daily", methods=["POST"])
@require_roles("PlatformAdmin")
def run_daily():
    now = clock.now()
    reminders_sent = 0
    programs_closed = 0
    applications_expired = 0
    offers_expired = 0

    # Sweep 1: dispatch due reminders (send_at <= now; equality dispatches),
    # processed in send_at ASC order, ties by created_at ASC.
    due = [r for r in db.all_records("reminders")
           if r["status"] == "SCHEDULED" and clock.parse_iso(r["send_at"]) <= now]
    due.sort(key=lambda r: (r["send_at"], r["created_at"], r["_seq"]))
    for r in due:
        db.mutate(r, status="SENT", sent_at=clock.now_iso())
        reminders_sent += 1

    # Sweep 2: close OPEN programs whose close has been reached; expire DRAFT
    # applications of CLOSED programs past their close; suppress their reminders.
    for p in db.all_records("programs"):
        if p["status"] == "OPEN" and now >= clock.parse_iso(p["application_close_at"]):
            db.mutate(p, status="CLOSED")
            programs_closed += 1
    for app in db.all_records("applications"):
        if app["status"] != "DRAFT":
            continue
        program = db.get("programs", app["program_id"])
        if (program is not None and program["status"] == "CLOSED"
                and now >= clock.parse_iso(program["application_close_at"])):
            db.mutate(app, status="EXPIRED")
            engine.suppress_reminders(app["id"])
            applications_expired += 1

    # Sweep 3: expire OFFERED awards whose offer_expires_at lies strictly before now.
    for a in db.all_records("awards"):
        if a["offer_status"] == "OFFERED" and now > clock.parse_iso(a["offer_expires_at"]):
            db.mutate(a, offer_status="EXPIRED")
            program = engine.program_of_award(a)
            engine.recompute_fund(db.get("award_funds", program["fund_id"]))
            engine.recompute_student(db.get("students", a["student_id"]))
            engine.waitlist_promotion(a)
            offers_expired += 1

    return success({
        "reminders_sent": reminders_sent,
        "programs_closed": programs_closed,
        "applications_expired": applications_expired,
        "offers_expired": offers_expired,
    })
