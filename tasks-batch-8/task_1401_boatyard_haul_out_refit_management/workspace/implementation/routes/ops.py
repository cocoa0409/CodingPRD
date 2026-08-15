"""Operations checkpoint (daily close) and the test-driving logical clock
(PRD 2.6, 3.11)."""

from flask import Blueprint

import clock
import db
import response
from errors import validation
from middleware import require_roles
from services import lifecycle, storage as storage_svc
from validation import get_body, parse_datetime_str
from .lift_slots import TERMINAL_SLOT_STATES

bp = Blueprint("ops", __name__)

ACCRUAL_JOB_STATES = ("ON_HARD", "WORK_IN_PROGRESS", "READY_FOR_SPLASH")


@bp.post("/yard/ops/run-daily-close")
@require_roles("YardManager")
def run_daily_close():
    get_body()  # accepts (and ignores) an optional body
    today = clock.today()
    now_dt = clock.now()

    # Step 1: expire certificates whose expiry_date is before the current date.
    expired_certificate_ids = []
    for cert in list(db.certificates.values()):
        if cert["status"] == "ACTIVE" and cert["_expiry"] < today:
            cert["status"] = "EXPIRED"
            db.touch(cert)
            expired_certificate_ids.append(cert["id"])

    # Step 2: stale BOOKED slots (scheduled_end in the past) become NO_SHOW;
    # a no-show haul-out returns its job HAUL_SCHEDULED -> INTAKE.
    no_show_slot_ids = []
    for slot in list(db.slots.values()):
        if slot["status"] == "BOOKED" and slot["_end"] < now_dt:
            slot["status"] = "NO_SHOW"
            db.touch(slot)
            no_show_slot_ids.append(slot["id"])
            if slot["kind"] == "HAUL_OUT":
                job = db.jobs.get(slot["job_id"])
                if job is not None and job["status"] == "HAUL_SCHEDULED":
                    job["status"] = "INTAKE"
                    db.touch(job)

    # Step 3: accrue storage for every on-hard job (idempotent per
    # last_accrual_date).
    storage_entries_posted = 0
    for job in list(db.jobs.values()):
        if job["status"] in ACCRUAL_JOB_STATES:
            storage_entries_posted += storage_svc.accrue_job(job, today)

    # Step 4: COMPLETE jobs with balance <= 0 become CLOSED.
    closed_job_ids = []
    for job in list(db.jobs.values()):
        if job["status"] == "COMPLETE" and storage_svc.ledger_balance(job["id"]) <= 0:
            job["status"] = "CLOSED"
            job["closed_at"] = today.isoformat()
            db.touch(job)
            closed_job_ids.append(job["id"])

    return response.success_object({
        "closed_date": today.isoformat(),
        "storage_entries_posted": storage_entries_posted,
        "expired_certificate_ids": expired_certificate_ids,
        "no_show_slot_ids": no_show_slot_ids,
        "closed_job_ids": closed_job_ids,
    })


@bp.post("/yard/_clock/set_current_utc")
@require_roles("YardManager")
def set_clock():
    body = get_body()
    raw = body.get("to_iso8601")
    if not isinstance(raw, str):
        raise validation("Field 'to_iso8601' is required and must be an ISO 8601 datetime string")
    dt = parse_datetime_str(raw, "to_iso8601")
    clock.set_current(dt)
    return response.success_object({"current_utc": raw})
