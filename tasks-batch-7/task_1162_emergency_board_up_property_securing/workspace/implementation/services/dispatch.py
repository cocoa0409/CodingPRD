"""Dispatch selection and offer/assignment cascade."""
from datetime import timedelta
import db
from db import clock, format_ts, iso_now
from errors import err
from services.common import (
    base_record, touch, recompute_active_assignment_count,
    find_accepted_or_arrived_assignment,
)

OFFER_EXPIRY_MINUTES = 30


def next_offer_seq(job_id):
    seqs = [a["offer_seq"] for a in db.assignments.values() if a["job_id"] == job_id]
    return (max(seqs) + 1) if seqs else 1


def active_assignment_count(sub_id):
    return sum(
        1 for a in db.assignments.values()
        if a["subcontractor_id"] == sub_id and a["status"] in ("ACCEPTED", "ARRIVED")
    )


def has_terminal_offer_on_job(sub_id, job_id):
    for a in db.assignments.values():
        if a["job_id"] == job_id and a["subcontractor_id"] == sub_id and a["status"] in ("DECLINED", "EXPIRED", "CANCELLED"):
            return True
    return False


def dispatch_selection(job, exclude_prior_offerees=False):
    """Return (subcontractor, coverage) chosen for the job, or None if pool empty."""
    prop = db.properties.get(job["property_id"])
    market_id = prop["market_id"]
    candidates = []
    for cov in db.coverages.values():
        if cov["market_id"] != market_id:
            continue
        if cov["status"] != "ACTIVE":
            continue
        sub = db.subcontractors.get(cov["subcontractor_id"])
        if sub is None or sub["status"] != "ACTIVE":
            continue
        active = active_assignment_count(sub["id"])
        if active >= cov["max_concurrent_jobs"]:
            continue
        if exclude_prior_offerees and has_terminal_offer_on_job(sub["id"], job["id"]):
            continue
        candidates.append((sub, cov))

    if not candidates:
        return None

    from services.common import reliability

    def key_fn(pair):
        sub, cov = pair
        lenient, _ = reliability(sub)
        return (-lenient, cov["rank"], sub["created_at"])

    candidates.sort(key=key_fn)
    return candidates[0]


def create_offer(job, subcontractor):
    now_dt = clock.now()
    a = base_record()
    a.update({
        "job_id": job["id"],
        "subcontractor_id": subcontractor["id"],
        "offer_seq": next_offer_seq(job["id"]),
        "status": "OFFERED",
        "offered_at": format_ts(now_dt),
        "offer_expires_at": format_ts(now_dt + timedelta(minutes=OFFER_EXPIRY_MINUTES)),
        "responded_at": None,
        "arrived_at": None,
        "response_minutes": None,
        "sla_breach": None,
    })
    db.assignments[a["id"]] = a
    return a


def run_reoffer_cascade(job, exclude_sub_id=None):
    """After DECLINE/EXPIRE/CANCEL: try to re-offer the job; else regress to INTAKE.
    Only meaningful when job is in DISPATCHED (no currently open offer remains).
    For ON_SITE jobs (ARRIVED assignment cancelled), regress to INTAKE when no
    re-offer possible."""
    # Check if there is still an open offer
    for a in db.assignments.values():
        if a["job_id"] == job["id"] and a["status"] == "OFFERED":
            return None
    # Also if there's still an ACCEPTED/ARRIVED assignment, no need
    cur = find_accepted_or_arrived_assignment(job["id"])
    if cur is not None:
        return None

    pair = dispatch_selection(job, exclude_prior_offerees=True)
    if pair is None:
        # regress to INTAKE
        if job["work_status"] in ("DISPATCHED", "ON_SITE"):
            job["work_status"] = "INTAKE"
            touch(job)
        return None
    sub, cov = pair
    offer = create_offer(job, sub)
    if job["work_status"] != "DISPATCHED":
        job["work_status"] = "DISPATCHED"
        job["dispatched_at"] = iso_now()
        touch(job)
    return offer


def expire_offer_and_cascade(assignment):
    """Lazy expiry: OFFERED -> EXPIRED, bump counter, run re-offer cascade."""
    assignment["status"] = "EXPIRED"
    touch(assignment)
    sub = db.subcontractors.get(assignment["subcontractor_id"])
    if sub is not None:
        sub["expired_offer_count"] = sub.get("expired_offer_count", 0) + 1
        touch(sub)
    job = db.jobs.get(assignment["job_id"])
    if job is not None:
        run_reoffer_cascade(job)
