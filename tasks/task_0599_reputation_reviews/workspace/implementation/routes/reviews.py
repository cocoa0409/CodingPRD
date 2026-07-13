"""Review ingest, moderation dimension, review lists, escalation lists."""

from flask import Blueprint, g, request

import calc
import store
import validation as v
from auth import endpoint, resolve_location, resolve_review
from envelope import created, ok, paginate
from errors import err
from services import (add_alert, assert_not_frozen, cancel_open_escalations,
                      open_escalation, recompute_location, review_escalations,
                      touch)

bp = Blueprint("reviews", __name__)

MODERATION_STATES = ("UNVERIFIED", "VERIFIED", "FLAGGED")
SENTIMENTS = ("POSITIVE", "NEUTRAL", "NEGATIVE")


@bp.post("/reputation/locations/<location_id>/reviews")
@endpoint(["PlatformAdmin"])
def ingest_review(location_id):
    loc = resolve_location(location_id)
    data = v.body()

    # priority 5 -- body-reference existence: the request's campaign must live
    # at the location being ingested into.
    linked_request = None
    raw_request_id = data.get("review_request_id")
    if raw_request_id is not None:
        if not isinstance(raw_request_id, str):
            raise err("ERR_INVALID_REQUEST", "Field 'review_request_id' must be a string.")
        linked_request = store.review_requests.get(raw_request_id)
        if linked_request is None:
            raise err("ERR_REQUEST_NOT_FOUND")
        campaign = store.campaigns[linked_request["campaign_id"]]
        if campaign["location_id"] != location_id:
            raise err("ERR_REQUEST_NOT_FOUND")

    # priority 6 -- well-formedness
    site = v.req_enum(data, "site", v.SITES)
    external_review_id = v.req_str(data, "external_review_id")
    author_name = v.req_str(data, "author_name")
    text = v.req_str(data, "text")
    rating = v.req_int(data, "rating", minimum=1, maximum=5)
    posted_at = v.req_datetime(data, "posted_at")

    # priority 8 -- FROZEN
    assert_not_frozen(loc)

    # priority 18 -- review uniqueness
    for r in store.reviews.values():
        if (r["location_id"] == location_id and r["site"] == site
                and r["external_review_id"] == external_review_id):
            raise err("ERR_DUPLICATE_EXTERNAL_REVIEW")

    sentiment = calc.review_sentiment(rating)

    rec = store.base_record()
    rec.update({
        "location_id": location_id,
        "review_request_id": linked_request["id"] if linked_request else None,
        "site": site,
        "external_review_id": external_review_id,
        "author_name": author_name,
        "text": text,
        "rating": rating,
        "posted_at": posted_at,
        "sentiment": sentiment,
        "moderation_state": "UNVERIFIED",
        "response_state": "NONE",
    })
    store.reviews[rec["id"]] = rec

    if sentiment == "NEGATIVE":
        open_escalation(rec)
        add_alert(loc["id"], "NEGATIVE_REVIEW",
                  "negative review ingested (rating %d)" % rating, rec["id"])

    # attribution: half-open [sent_at, sent_at + 14 days)
    if linked_request is not None and linked_request["status"] in ("SENT", "DELIVERED", "CLICKED"):
        if calc._in_window(linked_request["sent_at"], posted_at):
            linked_request["status"] = "CONVERTED"
            linked_request["converted_review_id"] = rec["id"]
            touch(linked_request)

    recompute_location(loc)
    return created(store.review_out(rec))


@bp.get("/reputation/reviews")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager", "ResponseAgent", "ComplianceOfficer"])
def list_reviews():
    moderation_state = v.enum_filter("moderation_state", MODERATION_STATES)
    sentiment = v.enum_filter("sentiment", SENTIMENTS)
    location_id = request.args.get("location_id")
    review_request_id = request.args.get("review_request_id")

    rows = list(store.reviews.values())
    if location_id is not None:
        loc = store.locations.get(location_id)
        if loc is None:
            raise err("ERR_LOCATION_NOT_FOUND")
        rows = [r for r in rows if r["location_id"] == location_id]
    if review_request_id is not None:
        if review_request_id not in store.review_requests:
            raise err("ERR_REQUEST_NOT_FOUND")
        rows = [r for r in rows if r["review_request_id"] == review_request_id]
    if moderation_state is not None:
        rows = [r for r in rows if r["moderation_state"] == moderation_state]
    if sentiment is not None:
        rows = [r for r in rows if r["sentiment"] == sentiment]

    rows = _visible(rows)
    return paginate(store.by_created(rows), store.review_out)


def _visible(rows):
    if g.role == "BusinessOwner":
        return [r for r in rows
                if store.locations[r["location_id"]]["business_id"] == g.user_id]
    if g.role == "LocationManager":
        return [r for r in rows if r["location_id"] == g.user_id]
    return rows


@bp.get("/reputation/reviews/<review_id>")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager", "ResponseAgent", "ComplianceOfficer"])
def get_review(review_id):
    review, _loc = resolve_review(review_id)
    return ok(store.review_out(review))


@bp.post("/reputation/reviews/<review_id>/verify")
@endpoint(["PlatformAdmin", "LocationManager"])
def verify_review(review_id):
    review, loc = resolve_review(review_id)
    assert_not_frozen(loc)

    state = review["moderation_state"]
    if state not in ("UNVERIFIED", "FLAGGED"):
        raise err("ERR_INVALID_STATE")

    reinstating = state == "FLAGGED"
    review["moderation_state"] = "VERIFIED"
    touch(review)

    if reinstating and review["sentiment"] == "NEGATIVE":
        open_escalation(review)

    recompute_location(loc)
    return ok(store.review_out(review))


@bp.post("/reputation/reviews/<review_id>/flag")
@endpoint(["PlatformAdmin", "LocationManager"])
def flag_review(review_id):
    review, loc = resolve_review(review_id)
    data = v.body()
    v.opt_str(data, "reason")

    assert_not_frozen(loc)

    if review["moderation_state"] not in ("UNVERIFIED", "VERIFIED"):
        raise err("ERR_INVALID_STATE")

    review["moderation_state"] = "FLAGGED"
    touch(review)

    cancel_open_escalations(review)
    recompute_location(loc)
    return ok(store.review_out(review))


@bp.get("/reputation/reviews/<review_id>/escalations")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager", "ComplianceOfficer"])
def list_review_escalations(review_id):
    review, _loc = resolve_review(review_id)
    return paginate(review_escalations(review), store.escalation_out)
