"""Cross-entity lifecycle cascades: holds, readiness, slot cancel, stand
release, job-cancel compensation (PRD 3.2/3.8/3.9/3.10, scaffold 1.2)."""

import db
from db import touch


def reevaluate_readiness(job):
    """A job becomes READY_FOR_SPLASH -- from ON_HARD or WORK_IN_PROGRESS --
    when at least one work order is COMPLETE, every work order is in
    {COMPLETE, CANCELLED}, and open_hold_count == 0 (PRD 3.10)."""
    if job["status"] not in ("ON_HARD", "WORK_IN_PROGRESS"):
        return
    if job["open_hold_count"] != 0:
        return
    wos = [w for w in db.work_orders.values() if w["job_id"] == job["id"]]
    if not any(w["status"] == "COMPLETE" for w in wos):
        return
    if not all(w["status"] in ("COMPLETE", "CANCELLED") for w in wos):
        return
    job["status"] = "READY_FOR_SPLASH"


def cancel_slot(slot, revert_haul_job=True):
    """BOOKED -> CANCELLED. A cancelled haul-out returns the job from
    HAUL_SCHEDULED to INTAKE unless this is part of the job-cancel cascade
    (the job itself is heading to CANCELLED there)."""
    slot["status"] = "CANCELLED"
    touch(slot)
    if revert_haul_job and slot["kind"] == "HAUL_OUT":
        job = db.jobs.get(slot["job_id"])
        if job is not None and job["status"] == "HAUL_SCHEDULED":
            job["status"] = "INTAKE"
            touch(job)


def release_assignment(asn):
    """ACTIVE -> RELEASED; row.stands_in_use -= stands_used; row.version += 1."""
    asn["status"] = "RELEASED"
    touch(asn)
    row = db.rows.get(asn["row_id"])
    if row is not None:
        row["stands_in_use"] -= asn["stands_used"]
        touch(row)


def open_hold(job, kind, source, note, source_event_id=None):
    """Hold-creation side effects, identical for MANUAL and AUTO_VIOLATION
    (PRD 3.9): open_hold_count += 1; READY_FOR_SPLASH -> WORK_IN_PROGRESS;
    every BOOKED SPLASH slot CANCELLED; every IN_PROGRESS work order ON_HOLD."""
    now = db.now_iso()
    hold = {
        "id": db.new_id(),
        "job_id": job["id"],
        "kind": kind,
        "note": note,
        "source": source,
        "source_event_id": source_event_id,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.holds[hold["id"]] = hold
    job["open_hold_count"] += 1
    if job["status"] == "READY_FOR_SPLASH":
        job["status"] = "WORK_IN_PROGRESS"
    for s in db.slots.values():
        if s["job_id"] == job["id"] and s["kind"] == "SPLASH" and s["status"] == "BOOKED":
            s["status"] = "CANCELLED"
            touch(s)
    for w in db.work_orders.values():
        if w["job_id"] == job["id"] and w["status"] == "IN_PROGRESS":
            w["status"] = "ON_HOLD"
            touch(w)
    touch(job)
    return hold


def release_hold(job, hold):
    """OPEN -> RELEASED; open_hold_count -= 1; at zero holds the ON_HOLD work
    orders resume to IN_PROGRESS and readiness re-evaluation runs (PRD 3.9)."""
    hold["status"] = "RELEASED"
    touch(hold)
    job["open_hold_count"] -= 1
    if job["open_hold_count"] == 0:
        for w in db.work_orders.values():
            if w["job_id"] == job["id"] and w["status"] == "ON_HOLD":
                w["status"] = "IN_PROGRESS"
                touch(w)
        reevaluate_readiness(job)
    touch(job)


NON_TERMINAL_WO_STATES = ("ESTIMATE", "APPROVED", "IN_PROGRESS", "ON_HOLD", "CHANGE_REQUESTED")


def cancel_job(job):
    """Job-cancel compensation set (PRD 3.2): BOOKED slots CANCELLED (no
    rebooking revert -- the job itself is being cancelled); ACTIVE stand
    assignments RELEASED (row decremented and bumped); non-terminal work
    orders CANCELLED; ledger entries deliberately untouched."""
    for s in list(db.slots.values()):
        if s["job_id"] == job["id"] and s["status"] == "BOOKED":
            cancel_slot(s, revert_haul_job=False)
    for a in list(db.assignments.values()):
        if a["job_id"] == job["id"] and a["status"] == "ACTIVE":
            release_assignment(a)
    for w in list(db.work_orders.values()):
        if w["job_id"] == job["id"] and w["status"] in NON_TERMINAL_WO_STATES:
            w["status"] = "CANCELLED"
            touch(w)
    job["status"] = "CANCELLED"
    touch(job)
