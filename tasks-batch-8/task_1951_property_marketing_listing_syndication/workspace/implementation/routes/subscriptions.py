from flask import Blueprint

import clock
from db import store
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_LISTING_NOT_ACTIVE,
    ERR_PORTAL_NOT_ACTIVE,
    ERR_SUBSCRIPTION_EXISTS,
)
from middleware import (
    authenticate, require_roles, get_body, not_found, paginate,
)
from response import success_object, success_list
from services.ops import stamp, touch, queue_job, pause_subscription
from services.serialize import subscription_json, job_json

bp = Blueprint("subscriptions", __name__)

READ_ROLES = ("ListingAgent", "MarketingCoordinator", "ComplianceOfficer",
              "MarketingDirector")
WRITE_ROLES = ("MarketingCoordinator", "MarketingDirector")
JOB_READ_ROLES = READ_ROLES + ("PortalWebhook",)


def _get_sub(sub_id):
    sub = store.subscriptions.get(sub_id)
    if sub is None:
        raise not_found("FeedSubscription not found")
    return sub


@bp.route("/listings/<listing_id>/feed-subscriptions", methods=["POST"])
def create_subscription(listing_id):
    _, role = authenticate()
    require_roles(role, WRITE_ROLES)
    listing = store.listings.get(listing_id)
    if listing is None:
        raise not_found("Listing not found")
    body = get_body()
    portal_id = body.get("portal_account_id")
    if portal_id is None:
        from middleware import invalid
        raise invalid("portal_account_id is required")
    portal = store.portals.get(portal_id)
    if portal is None:
        raise not_found("portal_account_id does not resolve")
    # Portal-active check precedes the duplicate check (PRD 3.5).
    if portal["status"] != "ACTIVE":
        raise ApiError(ERR_PORTAL_NOT_ACTIVE, 409,
                       "Portal account is not ACTIVE")
    if any(s["listing_id"] == listing["id"]
           and s["portal_account_id"] == portal["id"]
           and s["status"] in ("SUBSCRIBED", "PAUSED")
           for s in store.subscriptions.values()):
        raise ApiError(ERR_SUBSCRIPTION_EXISTS, 409,
                       "A live subscription already exists for this listing and portal")
    now = clock.now()
    sub = stamp({
        "listing_id": listing["id"],
        "portal_account_id": portal["id"],
        "status": "SUBSCRIBED",
    }, now)
    store.subscriptions[sub["id"]] = sub
    queue_job(sub, listing, "FULL_SYNC", now)
    return success_object(subscription_json(sub), status=201)


@bp.route("/listings/<listing_id>/feed-subscriptions", methods=["GET"])
def list_subscriptions(listing_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if listing_id not in store.listings:
        raise not_found("Listing not found")
    items = sorted(
        (s for s in store.subscriptions.values()
         if s["listing_id"] == listing_id),
        key=lambda s: (s["created_at"], s["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([subscription_json(s) for s in page],
                        limit, offset, total)


@bp.route("/feed-subscriptions/<sub_id>", methods=["GET"])
def get_subscription(sub_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    return success_object(subscription_json(_get_sub(sub_id)))


@bp.route("/feed-subscriptions/<sub_id>/pause", methods=["POST"])
def pause(sub_id):
    _, role = authenticate()
    require_roles(role, WRITE_ROLES)
    sub = _get_sub(sub_id)
    if sub["status"] != "SUBSCRIBED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "pause requires subscription status SUBSCRIBED")
    pause_subscription(sub, clock.now())
    return success_object(subscription_json(sub))


@bp.route("/feed-subscriptions/<sub_id>/resume", methods=["POST"])
def resume(sub_id):
    _, role = authenticate()
    require_roles(role, WRITE_ROLES)
    sub = _get_sub(sub_id)
    if sub["status"] != "PAUSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "resume requires subscription status PAUSED")
    listing = store.listings.get(sub["listing_id"])
    if listing is None or listing["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_LISTING_NOT_ACTIVE, 409,
                       "resume requires listing lifecycle ACTIVE")
    portal = store.portals.get(sub["portal_account_id"])
    if portal is None or portal["status"] != "ACTIVE":
        raise ApiError(ERR_PORTAL_NOT_ACTIVE, 409,
                       "resume requires portal status ACTIVE")
    now = clock.now()
    sub["status"] = "SUBSCRIBED"
    touch(sub, now)
    queue_job(sub, listing, "FULL_SYNC", now)
    return success_object(subscription_json(sub))


@bp.route("/feed-subscriptions/<sub_id>/jobs", methods=["GET"])
def sub_jobs(sub_id):
    _, role = authenticate()
    require_roles(role, JOB_READ_ROLES)
    sub = _get_sub(sub_id)
    items = sorted(
        (j for j in store.jobs.values()
         if j["feed_subscription_id"] == sub["id"]),
        key=lambda j: (j["created_at"], j["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([job_json(j) for j in page], limit, offset, total)
