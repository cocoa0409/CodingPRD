"""run-ops sweep: expire holds, advance follow-ups, recompute (PRD §3.9)."""
import clock
from db import db, touch
from util import add_days

GRACE_DAYS = 3


def run_ops(clinic):
    now = clock.now()
    clinic["ops_run_index"] += 1

    # Expire RESERVED holds strictly past their hold_expires_at.
    for q in db.queue_entries.values():
        if q["clinic_id"] != clinic["id"]:
            continue
        if q["status"] == "RESERVED" and q["hold_expires_at"] is not None:
            if now > q["hold_expires_at"]:
                q["status"] = "EXPIRED"
                touch(q)

    # Advance follow-up statuses for every discharge instruction.
    for d in db.discharge_instructions.values():
        if d["follow_up_status"] in ("NONE",):
            continue
        due = d["follow_up_due_at"]
        if due is None:
            continue
        # Advance at most one step per sweep (OVERDUE happens "on a later
        # run-ops" than the one that set DUE — §1.3 follow_up_due).
        if d["follow_up_status"] == "PENDING":
            if now >= due:
                d["follow_up_status"] = "DUE"
                touch(d)
        elif d["follow_up_status"] == "DUE":
            if now >= add_days(due, GRACE_DAYS):
                d["follow_up_status"] = "OVERDUE"
                touch(d)

    # Recompute is implicit (posture/depth/rooms are derived on read).
    touch(clinic)
