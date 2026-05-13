"""Test-harness sweep: survey expiry + supervision inactivity escalation + warning_state recompute."""

import clock
import db
from business_hours import business_seconds_between
from services import audit as audit_svc
from services import work_order_calc as calc

SURVEY_EXPIRY_BUSINESS_HOURS = 48
REMINDER_INTERVAL_BUSINESS_HOURS = 24
MAX_ESCALATION_LEVEL = 3


def run() -> dict:
    """Perform one pass. Returns a summary dict."""
    now_dt = clock.now()
    now_iso = clock.now_iso()

    # 1) Survey expiry
    surveys_expired = []
    for s in db.all_rows("satisfaction_surveys"):
        if s["status"] != "DISPATCHED":
            continue
        d = clock.parse_iso(s["dispatched_at"])
        bh = business_seconds_between(d, now_dt) / 3600.0
        if bh > SURVEY_EXPIRY_BUSINESS_HOURS:
            db.update_fields(s, {"status": "EXPIRED"})
            surveys_expired.append(s["id"])

    # 2) Supervision inactivity escalation
    tasks_escalated = []
    for t in db.all_rows("supervision_tasks"):
        if t["status"] not in ("OPEN", "ACKNOWLEDGED"):
            continue
        if int(t.get("escalation_level", 0)) >= MAX_ESCALATION_LEVEL:
            continue
        # baseline timestamp:
        candidates = [t["created_at"]]
        if t.get("last_reminder_at"):
            candidates.append(t["last_reminder_at"])
        # For OPEN, also consider latest WO activity (ACCEPT/OPINION_SUBMIT/RESOLVE).
        if t["status"] == "OPEN":
            la = audit_svc.latest_activity_timestamp(t["work_order_id"])
            if la:
                candidates.append(la)
        baseline = max(candidates)
        bh = business_seconds_between(clock.parse_iso(baseline), now_dt) / 3600.0
        if bh >= REMINDER_INTERVAL_BUSINESS_HOURS:
            new_level = int(t.get("escalation_level", 0)) + 1
            db.update_fields(t, {
                "status": "ESCALATED",
                "escalation_level": new_level,
                "last_reminder_at": now_iso,
            })
            tasks_escalated.append(t["id"])

    # 3) Recompute warning_state for every WO.
    for w in db.all_rows("work_orders"):
        new_state = calc.compute_warning_state(w)
        if new_state != w.get("warning_state"):
            w["warning_state"] = new_state
            # Recomputed state is not a mutation that bumps version per PRD — it's derived;
            # but the field is computed and read-time, so we don't bump.

    return {
        "surveys_expired": surveys_expired,
        "supervision_escalated": tasks_escalated,
    }
