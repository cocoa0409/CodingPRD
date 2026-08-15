from datetime import timedelta

from flask import Blueprint, request

import clock
from db import store
from errors import ApiError, ERR_JOB_NOT_DISPATCHED
from middleware import (
    authenticate, require_roles, get_body, f_str, not_found, paginate,
)
from response import success_object, success_list
from services.ops import touch
from services.serialize import job_json

bp = Blueprint("feed_events", __name__)

JOB_READ_ROLES = ("ListingAgent", "MarketingCoordinator", "ComplianceOfficer",
                  "MarketingDirector", "PortalWebhook")


def _get_job(job_id):
    job = store.jobs.get(job_id)
    if job is None:
        raise not_found("SyndicationJob not found")
    return job


@bp.route("/listings/<listing_id>/feed-events", methods=["GET"])
def list_feed_events(listing_id):
    _, role = authenticate()
    require_roles(role, JOB_READ_ROLES)
    if listing_id not in store.listings:
        raise not_found("Listing not found")
    job_type = request.args.get("job_type")
    status = request.args.get("status")
    items = sorted(
        (j for j in store.jobs.values() if j["listing_id"] == listing_id),
        key=lambda j: (j["created_at"], j["_seq"]))
    if job_type is not None:
        items = [j for j in items if j["job_type"] == job_type]
    if status is not None:
        items = [j for j in items if j["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([job_json(j) for j in page], limit, offset, total)


@bp.route("/feed-events/<job_id>/ack", methods=["POST"])
def ack(job_id):
    _, role = authenticate()
    require_roles(role, ("PortalWebhook",))
    job = _get_job(job_id)
    get_body()
    if job["status"] != "DISPATCHED":
        raise ApiError(ERR_JOB_NOT_DISPATCHED, 409,
                       "ack requires job status DISPATCHED")
    now = clock.now()
    job["status"] = "ACKED"
    job["completed_at"] = now
    job["propagation_delay_seconds"] = int(
        (now - job["dispatched_at"]).total_seconds())
    touch(job, now)
    # A TERMINAL_SYNC ack on a paused subscription of a listing that has left
    # the market completes the subscription (PRD 3.6).
    if job["job_type"] == "TERMINAL_SYNC":
        sub = store.subscriptions.get(job["feed_subscription_id"])
        listing = store.listings.get(job["listing_id"])
        if sub is not None and sub["status"] == "PAUSED" and listing is not None \
                and listing["lifecycle_status"] in ("WITHDRAWN", "EXPIRED", "SOLD"):
            sub["status"] = "COMPLETED"
            touch(sub, now)
    return success_object(job_json(job))


@bp.route("/feed-events/<job_id>/fail", methods=["POST"])
def fail(job_id):
    _, role = authenticate()
    require_roles(role, ("PortalWebhook",))
    job = _get_job(job_id)
    body = get_body()
    error_code = f_str(body, "error_code", required=True)
    if job["status"] != "DISPATCHED":
        raise ApiError(ERR_JOB_NOT_DISPATCHED, 409,
                       "fail requires job status DISPATCHED")
    now = clock.now()
    job["failure_code"] = error_code
    if job["attempt_count"] < 3:
        job["status"] = "RETRY_QUEUED"
        job["scheduled_at"] = now + timedelta(
            seconds=60 * (2 ** job["attempt_count"]))
    else:
        job["status"] = "DEAD_LETTER"
        job["completed_at"] = now
    touch(job, now)
    return success_object(job_json(job))
