"""Test-clock and time-driven sweeps."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask

from ..audit import emit_sync_event, write_payment_event
from ..auth import require_auth
from ..clock import CLOCK, now_dt, parse_iso
from ..errors import ApiError
from ..store import LOCK, bump_version, get_store
from ._helpers import get_json_body, ok


def _run_sweeps() -> None:
    now = now_dt()
    # 1) Appointment NO_SHOW: SCHEDULED past scheduled_end + 60 min
    for appt in list(get_store().appointments.values()):
        if appt["status"] == "SCHEDULED":
            sched_end = parse_iso(appt["scheduled_end"])
            if now > sched_end + timedelta(minutes=60):
                appt["status"] = "NO_SHOW"
                bump_version(appt)
    # 2) FollowUp MISSED: PENDING past due_at + 7 days
    for fu in list(get_store().followups.values()):
        if fu["status"] == "PENDING":
            due = parse_iso(fu["due_at"])
            if now > due + timedelta(days=7):
                fu["status"] = "MISSED"
                bump_version(fu)
    # 3) InstallmentPlan IN_DEFAULT
    for inst in list(get_store().installment_plans.values()):
        if inst["status"] == "ACTIVE":
            for e in inst["schedule"]:
                if e["status"] == "PENDING":
                    due = parse_iso(e["due_date"])
                    if now > due + timedelta(days=7):
                        inst["status"] = "IN_DEFAULT"
                        inst["default_strike_count"] = int(inst.get("default_strike_count") or 0) + 1
                        bump_version(inst)
                        write_payment_event(inst["id"], "COLLECTION_NOTICE", 0)
                        emit_sync_event("FINANCE_PARTNER", "DEFAULT_STRIKE", {"installment_plan_id": inst["id"]})
                        break


def register(app: Flask) -> None:
    @app.route("/_clock/advance", methods=["POST"])
    @require_auth("MedicalDirector")
    def advance_clock():
        body = get_json_body()
        if "seconds" not in body:
            raise ApiError("ERR_INVALID_INPUT", "seconds required")
        s = body["seconds"]
        if not isinstance(s, (int, float)) or isinstance(s, bool) or s < 0:
            raise ApiError("ERR_INVALID_INPUT", "seconds must be a non-negative number")
        with LOCK:
            CLOCK.advance_seconds(float(s))
            _run_sweeps()
        return ok({})
