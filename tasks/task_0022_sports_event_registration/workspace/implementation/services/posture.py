"""Compute Event.posture."""
import db


def recompute_posture(event_id: str) -> str:
    # Find all samples in this event
    sample_ids = {s["id"] for s in db.doping_samples.values() if s["event_id"] == event_id}
    open_sanctions = 0
    appealed = False
    for sr in db.sanction_records.values():
        if sr["sample_id"] not in sample_ids:
            continue
        if sr["status"] in ("ISSUED", "APPEALED"):
            open_sanctions += 1
        if sr["status"] == "APPEALED":
            appealed = True
    pending_appeals = 0
    for ap in db.appeals.values():
        sr = db.sanction_records.get(ap["sanction_id"])
        if not sr:
            continue
        if sr["sample_id"] not in sample_ids:
            continue
        if ap["status"] == "PENDING":
            pending_appeals += 1
    if pending_appeals > 0 or appealed:
        posture = "FROZEN"
    elif open_sanctions > 0:
        posture = "UNDER_REVIEW"
    else:
        posture = "CLEAN"
    ev = db.events.get(event_id)
    if ev and ev.get("posture") != posture:
        ev["posture"] = posture
        db.stamp_update(ev)
    return posture
