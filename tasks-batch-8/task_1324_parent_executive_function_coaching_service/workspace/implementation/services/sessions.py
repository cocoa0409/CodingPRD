"""Cadence window and coach schedule-conflict checks."""
from datetime import timedelta

import db
import errors as E

DAY = 86400
WORKSHOP_BUFFER = timedelta(minutes=15)


def check_cadence(plan, new_start):
    """ERR_CADENCE_WINDOW_VIOLATION when outside the first-session or gap windows."""
    anchors = [
        s for s in db.sessions.values()
        if s["plan_id"] == plan["id"]
        and s["attendance_state"] in ("SCHEDULED", "COMPLETED", "NO_SHOW")
    ]
    if not anchors:
        activated = plan["activated_at_dt"]
        delta = (new_start - activated).total_seconds()
        if delta < 0 or delta > 14 * DAY:
            E.raise_error(E.ERR_CADENCE_WINDOW_VIOLATION,
                          "First session must start within [0, 14] days of plan activation")
        return
    anchors.sort(key=lambda s: (s["scheduled_start_dt"], s["created_at"], s["seq"]), reverse=True)
    last = anchors[0]
    gap_days = (new_start - last["scheduled_start_dt"]).total_seconds() / DAY
    if plan["cadence"] == "WEEKLY":
        lo, hi = 4, 10
    else:
        lo, hi = 11, 17
    if gap_days < lo or gap_days > hi:
        E.raise_error(E.ERR_CADENCE_WINDOW_VIOLATION,
                      "Gap of %s days violates %s cadence window [%s, %s]"
                      % (gap_days, plan["cadence"], lo, hi))


def check_coach_conflicts(coach_id, new_start, new_end):
    # Rule A: half-open overlap vs the coach's SCHEDULED sessions.
    for s in db.sessions.values():
        if s["coach_id"] == coach_id and s["attendance_state"] == "SCHEDULED":
            if new_start < s["scheduled_end_dt"] and new_end > s["scheduled_start_dt"]:
                E.raise_error(E.ERR_COACH_DOUBLE_BOOKED,
                              "Coach has an overlapping scheduled session")
    # Rule B: strict 15-minute buffered overlap vs coach's OPEN/LOCKED workshops.
    for w in db.workshops.values():
        if w["coach_id"] == coach_id and w["status"] in ("OPEN", "LOCKED"):
            if new_start < w["window_end_dt"] + WORKSHOP_BUFFER and new_end > w["window_start_dt"] - WORKSHOP_BUFFER:
                E.raise_error(E.ERR_COACH_BUFFER_CONFLICT,
                              "Session within 15-minute buffer of a coach workshop")
