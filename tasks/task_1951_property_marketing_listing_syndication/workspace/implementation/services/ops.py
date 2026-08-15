"""Mutation helpers: record stamping, event log, job queueing/supersede,
cascades, fair-housing scan."""
import uuid

from db import store
from errors import ApiError, ERR_FAIR_HOUSING_VIOLATION
from services.derived import LIVE_JOB_STATUSES, display_price_cents

FAIR_HOUSING_PHRASES = (
    "no children",
    "adults only",
    "not suitable for families",
    "christian neighborhood",
    "no wheelchairs",
    "english speakers only",
)


def scan_fair_housing(remarks):
    if not remarks:
        return
    low = remarks.lower()
    for phrase in FAIR_HOUSING_PHRASES:
        if phrase in low:
            raise ApiError(
                ERR_FAIR_HOUSING_VIOLATION, 422,
                f"marketing remarks contain prohibited phrase: {phrase}")


def stamp(record, now, light=False):
    record["id"] = str(uuid.uuid4())
    record["created_at"] = now
    store.insert_counter += 1
    record["_seq"] = store.insert_counter
    if not light:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record, now):
    record["updated_at"] = now
    record["version"] += 1


def append_event(listing, now, event_type, **kw):
    seq = store.event_seq.get(listing["id"], 0) + 1
    store.event_seq[listing["id"]] = seq
    ev = {
        "listing_id": listing["id"],
        "seq": seq,
        "event_type": event_type,
        "old_price_cents": kw.get("old_price_cents"),
        "new_price_cents": kw.get("new_price_cents"),
        "old_remarks": kw.get("old_remarks"),
        "new_remarks": kw.get("new_remarks"),
        "from_lifecycle": kw.get("from_lifecycle"),
        "to_lifecycle": kw.get("to_lifecycle"),
    }
    stamp(ev, now, light=True)
    store.events[ev["id"]] = ev
    return ev


def queue_job(sub, listing, job_type, now):
    """Create a QUEUED job; a still-QUEUED job of the same type for the same
    subscription is superseded (PRD 3.6)."""
    for j in list(store.jobs.values()):
        if j["feed_subscription_id"] == sub["id"] and j["job_type"] == job_type \
                and j["status"] == "QUEUED":
            j["status"] = "SUPERSEDED"
            j["completed_at"] = now
            touch(j, now)
    portal = store.portals.get(sub["portal_account_id"])
    job = {
        "feed_subscription_id": sub["id"],
        "listing_id": listing["id"],
        "job_type": job_type,
        "status": "QUEUED",
        "attempt_count": 0,
        "scheduled_at": now,
        "dispatched_at": None,
        "completed_at": None,
        "propagation_delay_seconds": None,
        "payload_display_price_cents": (
            display_price_cents(listing["list_price_cents"], portal) if portal else None),
        "failure_code": None,
    }
    stamp(job, now)
    store.jobs[job["id"]] = job
    return job


def cancel_live_jobs(subscription_id, now):
    for j in store.jobs.values():
        if j["feed_subscription_id"] == subscription_id \
                and j["status"] in LIVE_JOB_STATUSES:
            j["status"] = "CANCELLED"
            j["completed_at"] = now
            touch(j, now)


def pause_subscription(sub, now):
    sub["status"] = "PAUSED"
    touch(sub, now)
    cancel_live_jobs(sub["id"], now)


def cancel_scheduled_windows(listing_id, now):
    for w in store.windows.values():
        if w["listing_id"] == listing_id and w["status"] == "SCHEDULED":
            w["status"] = "CANCELLED"
            touch(w, now)


def queue_jobs_for_subscribed_subs(listing, job_type, now):
    for sub in store.subscriptions.values():
        if sub["listing_id"] == listing["id"] and sub["status"] == "SUBSCRIBED":
            queue_job(sub, listing, job_type, now)


def lifecycle_transition(listing, to_status, now, terminal=False,
                         queue_terminal_sync=False):
    """Shared cascade for leaving the market / compliance hold (PRD 3.3, 3.4).

    Parent version increments exactly once for the transition; each cascaded
    child gets its own timestamp + version bump (PRD 2.5)."""
    old = listing["lifecycle_status"]
    if terminal:
        listing["terminal_entered_at"] = now
        listing["terminal_price_cents"] = listing["list_price_cents"]
    listing["lifecycle_status"] = to_status
    append_event(listing, now, "STATUS_CHANGE",
                 from_lifecycle=old, to_lifecycle=to_status)
    touch(listing, now)
    for sub in store.subscriptions.values():
        if sub["listing_id"] == listing["id"] and sub["status"] == "SUBSCRIBED":
            pause_subscription(sub, now)
            if queue_terminal_sync:
                queue_job(sub, listing, "TERMINAL_SYNC", now)
    cancel_scheduled_windows(listing["id"], now)
