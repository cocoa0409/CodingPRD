"""Review requests: list, read, delivery-connector callbacks, cancellation."""

from flask import Blueprint, g, request

import store
import validation as v
from auth import endpoint, resolve_request
from envelope import ok, paginate
from errors import err
from services import assert_not_frozen, refresh_campaign_billing, touch

bp = Blueprint("requests", __name__)

REQUEST_STATUSES = ("QUEUED", "SENT", "DELIVERED", "CLICKED", "CONVERTED", "FAILED", "SUPPRESSED")


def _visible(rows):
    """Scope a global list to the acting tenant."""
    if g.role == "BusinessOwner":
        keep = []
        for r in rows:
            campaign = store.campaigns[r["campaign_id"]]
            loc = store.locations[campaign["location_id"]]
            if loc["business_id"] == g.user_id:
                keep.append(r)
        return keep
    if g.role == "LocationManager":
        return [r for r in rows
                if store.campaigns[r["campaign_id"]]["location_id"] == g.user_id]
    return rows


@bp.get("/reputation/review-requests")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def list_requests():
    status = v.enum_filter("status", REQUEST_STATUSES)
    campaign_id = request.args.get("campaign_id")
    contact_id = request.args.get("contact_id")

    rows = list(store.review_requests.values())
    if campaign_id is not None:
        if campaign_id not in store.campaigns:
            raise err("ERR_CAMPAIGN_NOT_FOUND")
        rows = [r for r in rows if r["campaign_id"] == campaign_id]
    if contact_id is not None:
        if contact_id not in store.contacts:
            raise err("ERR_CONTACT_NOT_FOUND")
        rows = [r for r in rows if r["contact_id"] == contact_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    return paginate(store.by_created(_visible(rows)), store.request_out)


@bp.get("/reputation/review-requests/<request_id>")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def get_request(request_id):
    req, _campaign, _loc = resolve_request(request_id)
    return ok(store.request_out(req))


@bp.post("/reputation/review-requests/<request_id>/events")
@endpoint(["PlatformAdmin"])
def request_event(request_id):
    req, campaign, loc = resolve_request(request_id)
    data = v.body()
    event_type = v.req_enum(data, "event_type", v.EVENT_TYPES)

    assert_not_frozen(loc)

    status = req["status"]
    if event_type == "DELIVERED":
        if status != "SENT":
            raise err("ERR_INVALID_STATE")
        req["status"] = "DELIVERED"
    elif event_type == "CLICKED":
        if status != "DELIVERED":
            raise err("ERR_INVALID_STATE")
        req["status"] = "CLICKED"
    else:  # FAILED -- the credit stays consumed, a failed delivery is billable
        if status != "SENT":
            raise err("ERR_INVALID_STATE")
        req["status"] = "FAILED"

    touch(req)
    refresh_campaign_billing(campaign)
    touch(campaign)
    return ok(store.request_out(req))


@bp.post("/reputation/review-requests/<request_id>/cancel")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager"])
def cancel_request(request_id):
    req, campaign, loc = resolve_request(request_id)
    assert_not_frozen(loc)
    if req["status"] != "QUEUED":
        raise err("ERR_INVALID_STATE")

    req["status"] = "SUPPRESSED"
    touch(req)
    campaign["credits_reserved"] -= 1
    campaign["credits_released"] += 1
    refresh_campaign_billing(campaign)
    touch(campaign)
    return ok(store.request_out(req))
