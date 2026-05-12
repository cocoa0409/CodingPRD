"""Periodic sweep helpers — Quote EXPIRED, Milestone OVERDUE."""
import db


def run_sweep():
    clock = db.now_clock()
    # Quotes: OFFERED -> EXPIRED if clock >= valid_until
    for q in db.quotes.values():
        if q["status"] == "OFFERED" and clock >= int(q["valid_until"]):
            q["status"] = "EXPIRED"
            db.bump(q)
    # Milestones: PENDING/IN_PROGRESS -> OVERDUE if clock >= due_at
    for m in db.milestones.values():
        if m["status"] in ("PENDING", "IN_PROGRESS") and clock >= int(m["due_at"]):
            m["status"] = "OVERDUE"
            db.bump(m)
