from datetime import timedelta

from flask import Blueprint

import clock
from db import store
from middleware import authenticate, require_roles, get_body, f_dt
from response import success_object
from services.ops import lifecycle_transition, touch

bp = Blueprint("admin", __name__)

BLACKOUT_BUFFER = timedelta(minutes=15)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = authenticate()
    require_roles(role, ("MarketingDirector",))
    body = get_body()
    target = f_dt(body, "to_iso8601", required=True)
    clock.set_now(target)
    return success_object({"current_utc": clock.iso_fmt(clock.now())})


def _in_buffered_blackout(portal_id, now):
    for b in store.blackouts.values():
        if b["portal_account_id"] != portal_id:
            continue
        if (b["starts_at"] - BLACKOUT_BUFFER) <= now <= (
                b["ends_at"] + BLACKOUT_BUFFER):
            return True
    return False


@bp.route("/_sweeps/run", methods=["POST"])
def run_sweep():
    _, role = authenticate()
    require_roles(role, ("MarketingDirector",))
    get_body()
    now = clock.now()
    # 1) Expire due ACTIVE listings.
    expired_ids = []
    due_listings = sorted(store.listings.values(),
                          key=lambda l: (l["created_at"], l["_seq"]))
    for listing in due_listings:
        if listing["lifecycle_status"] == "ACTIVE" \
                and now >= listing["listing_expires_on"]:
            lifecycle_transition(listing, "EXPIRED", now,
                                 terminal=True, queue_terminal_sync=True)
            expired_ids.append(listing["id"])
    # 2) Dispatch due jobs in batch order: scheduled_at ASC, created_at ASC.
    candidates = sorted(
        (j for j in store.jobs.values()
         if j["status"] in ("QUEUED", "RETRY_QUEUED")
         and j["scheduled_at"] <= now),
        key=lambda j: (j["scheduled_at"], j["created_at"], j["_seq"]))
    dispatched_ids = []
    deferred_ids = []
    for job in candidates:
        sub = store.subscriptions.get(job["feed_subscription_id"])
        portal = store.portals.get(sub["portal_account_id"]) if sub else None
        if portal is None or portal["status"] != "ACTIVE":
            deferred_ids.append(job["id"])
            continue
        if _in_buffered_blackout(portal["id"], now):
            deferred_ids.append(job["id"])
            continue
        job["status"] = "DISPATCHED"
        job["dispatched_at"] = now
        job["attempt_count"] += 1
        touch(job, now)
        dispatched_ids.append(job["id"])
    # 3) Postures are derived at read; nothing to persist.
    return success_object({
        "expired_listing_ids": expired_ids,
        "dispatched_job_ids": dispatched_ids,
        "deferred_job_ids": deferred_ids,
    })
