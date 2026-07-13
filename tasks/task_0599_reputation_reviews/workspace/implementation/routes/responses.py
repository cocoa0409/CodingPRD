"""The reply workflow: draft, submit, approve, reject, revise, publish."""

from flask import Blueprint, g, request

import store
import validation as v
from auth import endpoint, resolve_response, resolve_review
from envelope import created, ok, paginate
from errors import err
from services import (assert_not_frozen, recompute_location,
                      resolve_open_escalations, touch)

bp = Blueprint("responses", __name__)

RESPONSE_STATES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "PUBLISHED")


@bp.post("/reputation/reviews/<review_id>/responses")
@endpoint(["PlatformAdmin", "ResponseAgent"])
def create_response(review_id):
    review, loc = resolve_review(review_id)
    business_id = loc["business_id"]
    data = v.body()

    # priority 5 -- body-reference existence and tenancy
    template = None
    raw_template_id = data.get("template_id")
    if raw_template_id is not None:
        if not isinstance(raw_template_id, str):
            raise err("ERR_INVALID_REQUEST", "Field 'template_id' must be a string.")
        template = store.templates.get(raw_template_id)
        if template is None or template["business_id"] != business_id:
            raise err("ERR_TEMPLATE_NOT_FOUND")

    # priority 6 -- well-formedness
    body_text = v.req_str(data, "body")
    expected_version = v.req_int(data, "expected_review_version")

    # priority 7 -- OCC
    if expected_version != review["version"]:
        raise err("ERR_STALE_VERSION")

    # priority 8 -- FROZEN
    assert_not_frozen(loc)

    # priority 10 -- state legality
    if review["moderation_state"] == "FLAGGED":
        raise err("ERR_INVALID_STATE")
    if review["response_state"] != "NONE":
        raise err("ERR_INVALID_STATE")

    # priority 14 -- template rating band
    if template is not None:
        if not (template["min_rating"] <= review["rating"] <= template["max_rating"]):
            raise err("ERR_TEMPLATE_RATING_MISMATCH")

    rec = store.base_record()
    rec.update({
        "review_id": review["id"],
        "template_id": template["id"] if template else None,
        "body": body_text,
        "state": "DRAFT",
        "drafted_by_user_id": g.user_id,
        "approved_by_user_id": None,
        "rejection_reason": None,
        "revision_count": 0,
        "published_at": None,
    })
    store.review_responses[rec["id"]] = rec

    review["response_state"] = "DRAFTED"
    touch(review)

    return created(store.response_out(rec))


@bp.get("/reputation/review-responses")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager", "ResponseAgent", "ComplianceOfficer"])
def list_responses():
    state = v.enum_filter("state", RESPONSE_STATES)
    review_id = request.args.get("review_id")
    template_id = request.args.get("template_id")

    rows = list(store.review_responses.values())
    if review_id is not None:
        if review_id not in store.reviews:
            raise err("ERR_REVIEW_NOT_FOUND")
        rows = [r for r in rows if r["review_id"] == review_id]
    if template_id is not None:
        if template_id not in store.templates:
            raise err("ERR_TEMPLATE_NOT_FOUND")
        rows = [r for r in rows if r["template_id"] == template_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]

    if g.role in ("BusinessOwner", "LocationManager"):
        keep = []
        for r in rows:
            review = store.reviews[r["review_id"]]
            loc = store.locations[review["location_id"]]
            if g.role == "BusinessOwner" and loc["business_id"] == g.user_id:
                keep.append(r)
            elif g.role == "LocationManager" and loc["id"] == g.user_id:
                keep.append(r)
        rows = keep

    return paginate(store.by_created(rows), store.response_out)


@bp.get("/reputation/review-responses/<response_id>")
@endpoint(["PlatformAdmin", "BusinessOwner", "LocationManager", "ResponseAgent", "ComplianceOfficer"])
def get_response(response_id):
    resp, _review, _loc = resolve_response(response_id)
    return ok(store.response_out(resp))


@bp.post("/reputation/review-responses/<response_id>/submit")
@endpoint(["PlatformAdmin", "ResponseAgent"])
def submit_response(response_id):
    resp, review, loc = resolve_response(response_id)
    assert_not_frozen(loc)
    if resp["state"] != "DRAFT":
        raise err("ERR_INVALID_STATE")

    template = store.templates.get(resp["template_id"]) if resp["template_id"] else None
    auto_approve = template is not None and template["requires_approval"] is False

    if auto_approve:
        # The conditional feature flag collapses submit+approve into one hop.
        resp["state"] = "APPROVED"
        resp["approved_by_user_id"] = None
        review["response_state"] = "APPROVED"
    else:
        resp["state"] = "PENDING_APPROVAL"
        review["response_state"] = "AWAITING_APPROVAL"

    touch(resp)
    touch(review)
    return ok(store.response_out(resp))


@bp.post("/reputation/review-responses/<response_id>/approve")
@endpoint(["PlatformAdmin", "ComplianceOfficer"])
def approve_response(response_id):
    resp, review, loc = resolve_response(response_id)
    assert_not_frozen(loc)
    if resp["state"] != "PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE")
    if g.user_id == resp["drafted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES")

    resp["state"] = "APPROVED"
    resp["approved_by_user_id"] = g.user_id
    touch(resp)

    review["response_state"] = "APPROVED"
    touch(review)
    return ok(store.response_out(resp))


@bp.post("/reputation/review-responses/<response_id>/reject")
@endpoint(["PlatformAdmin", "ComplianceOfficer"])
def reject_response(response_id):
    resp, review, loc = resolve_response(response_id)
    data = v.body()
    rejection_reason = v.req_str(data, "rejection_reason")

    assert_not_frozen(loc)
    if resp["state"] != "PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE")
    if g.user_id == resp["drafted_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES")

    resp["state"] = "REJECTED"
    resp["rejection_reason"] = rejection_reason
    touch(resp)
    # The review's reply dimension deliberately stays at AWAITING_APPROVAL.
    return ok(store.response_out(resp))


@bp.post("/reputation/review-responses/<response_id>/revise")
@endpoint(["PlatformAdmin", "ResponseAgent"])
def revise_response(response_id):
    resp, review, loc = resolve_response(response_id)
    data = v.body()
    body_text = v.req_str(data, "body")

    assert_not_frozen(loc)
    if resp["state"] != "REJECTED":
        raise err("ERR_INVALID_STATE")

    resp["body"] = body_text
    resp["state"] = "DRAFT"
    resp["revision_count"] += 1
    touch(resp)

    review["response_state"] = "DRAFTED"
    touch(review)
    return ok(store.response_out(resp))


@bp.post("/reputation/review-responses/<response_id>/publish")
@endpoint(["PlatformAdmin", "ComplianceOfficer"])
def publish_response(response_id):
    resp, review, loc = resolve_response(response_id)
    assert_not_frozen(loc)
    if resp["state"] != "APPROVED":
        raise err("ERR_INVALID_STATE")

    # priority 15 -- publish demands a live channel
    listing = None
    for li in store.listings.values():
        if li["location_id"] == review["location_id"] and li["site"] == review["site"]:
            listing = li
            break
    if listing is None or listing["sync_state"] != "CONNECTED":
        raise err("ERR_LISTING_NOT_CONNECTED")

    resp["state"] = "PUBLISHED"
    resp["published_at"] = store.now()
    touch(resp)

    # CASCADE LINK 1 -> 2 -> 3
    review["response_state"] = "RESPONDED"
    touch(review)
    resolve_open_escalations(review)
    recompute_location(loc)

    return ok(store.response_out(resp))
