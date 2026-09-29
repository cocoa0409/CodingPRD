"""Content change governance: two review tracks, one join, four cascade hops (PRD 3.5)."""
from flask import Blueprint, g, request

import calc
import envelope
import recompute
import validate
from auth import ALL_ROLES, endpoint
from entities import (change_request_out, get_change_request, get_content_version, get_product,
                      get_retailer)
from errors import ApiError
from store import base_row, db, in_order, now, touch

bp = Blueprint("governance", __name__)

TRACKS = ("LEGAL", "BRAND")
DECISIONS = ("APPROVED", "REJECTED")
TRACK_ROLE = {"LEGAL": "LegalReviewer", "BRAND": "BrandGovernanceApprover"}
TRACK_STATE_FIELD = {"LEGAL": "legal_review_state", "BRAND": "brand_review_state"}
TRACK_REVIEWER_FIELD = {"LEGAL": "legal_reviewer_user_id", "BRAND": "brand_reviewer_user_id"}
OTHER_TRACK = {"LEGAL": "BRAND", "BRAND": "LEGAL"}


@bp.route("/change-requests", methods=["POST"])
@endpoint(["ContentAuthor"])
def create_change_request():
    data = validate.body()
    product_id = validate.req_str(data, "product_id", 1)
    retailer_id = validate.req_str(data, "retailer_id", 1)
    target_id = validate.req_str(data, "target_content_version_id", 1)
    rationale = validate.req_str(data, "rationale", 1, 500)
    retailer = get_retailer(retailer_id)
    product = get_product(product_id)
    target = get_content_version(target_id)
    if target["state"] != "DRAFT":
        raise ApiError("ERR_VERSION_NOT_DRAFT")
    change_request = base_row()
    change_request.update({
        "product_id": product["id"],
        "retailer_id": retailer["id"],
        "target_content_version_id": target["id"],
        "rationale": rationale,
        "state": "DRAFT",
        "legal_review_state": "PENDING",
        "brand_review_state": "PENDING",
        "author_user_id": g.user_id,
        "legal_reviewer_user_id": None,
        "brand_reviewer_user_id": None,
        "submitted_at": None,
        "decided_at": None,
    })
    db.change_requests[change_request["id"]] = change_request
    return envelope.created(change_request_out(change_request))


@bp.route("/change-requests/<row_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_change_request(row_id):
    return envelope.ok(change_request_out(get_change_request(row_id)))


@bp.route("/change-requests", methods=["GET"])
@endpoint(ALL_ROLES)
def list_change_requests():
    limit, offset = envelope.page_params()
    rows = in_order(list(db.change_requests.values()))
    for arg in ("product_id", "retailer_id", "target_content_version_id", "state"):
        value = request.args.get(arg)
        if value is not None:
            rows = [r for r in rows if r.get(arg) == value]
    return envelope.paged_with(rows, change_request_out, limit, offset)


@bp.route("/change-requests/<row_id>/submit", methods=["POST"])
@endpoint(["ContentAuthor"])
def submit_change_request(row_id):
    change_request = get_change_request(row_id)
    listing = calc.find_listing(change_request["product_id"], change_request["retailer_id"])
    if listing is None:
        raise ApiError("ERR_LISTING_NOT_FOUND")
    retailer = db.retailers.get(change_request["retailer_id"])
    if retailer is None or retailer["status"] != "ACTIVE":
        raise ApiError("ERR_RETAILER_NOT_ACTIVE")
    target = db.content_versions.get(change_request["target_content_version_id"])
    if target is None or target["state"] != "DRAFT":
        raise ApiError("ERR_VERSION_NOT_DRAFT")
    if change_request["state"] != "DRAFT":
        raise ApiError("ERR_CHANGE_REQUEST_NOT_DRAFT")
    change_request["state"] = "IN_REVIEW"
    change_request["legal_review_state"] = "PENDING"
    change_request["brand_review_state"] = "PENDING"
    change_request["submitted_at"] = now()
    touch(change_request)
    # Content freeze: the revision under review can no longer be edited.
    target["state"] = "IN_REVIEW"
    touch(target)
    return envelope.ok(change_request_out(change_request))


@bp.route("/change-requests/<row_id>/reviews", methods=["POST"])
@endpoint(["LegalReviewer", "BrandGovernanceApprover"])
def review_change_request(row_id):
    data = validate.body()
    raw_track = data.get("track")
    # Step 3 -- the acting role must own the named track.
    if isinstance(raw_track, str) and raw_track in TRACKS:
        if TRACK_ROLE[raw_track] != g.role:
            raise ApiError("ERR_TRACK_ROLE_MISMATCH")
    change_request = get_change_request(row_id)
    # Step 5 -- the author may never decide either track.
    if g.user_id == change_request.get("author_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    # Step 6 -- the two-person rule against the other track's recorded reviewer.
    if isinstance(raw_track, str) and raw_track in TRACKS:
        other = change_request.get(TRACK_REVIEWER_FIELD[OTHER_TRACK[raw_track]])
        if other is not None and other == g.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    track = validate.req_enum(data, "track", TRACKS)
    decision = validate.req_enum(data, "decision", DECISIONS)
    expected_product_version = validate.req_int(data, "expected_product_version")
    product = get_product(change_request["product_id"])
    if expected_product_version != product["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if change_request["state"] != "IN_REVIEW":
        raise ApiError("ERR_CHANGE_REQUEST_NOT_IN_REVIEW")
    if change_request[TRACK_STATE_FIELD[track]] != "PENDING":
        raise ApiError("ERR_TRACK_ALREADY_DECIDED")

    target = db.content_versions.get(change_request["target_content_version_id"])
    change_request[TRACK_STATE_FIELD[track]] = decision
    change_request[TRACK_REVIEWER_FIELD[track]] = g.user_id

    if decision == "REJECTED":
        # Short-circuit: the aggregate rejects even while the other track is PENDING.
        change_request["state"] = "REJECTED"
        change_request["decided_at"] = now()
        touch(change_request)
        if target is not None:
            target["state"] = "DRAFT"
            touch(target)
    elif (change_request["legal_review_state"] == "APPROVED"
          and change_request["brand_review_state"] == "APPROVED"):
        _approval_join(change_request, target, product)
    else:
        # Self-loop: one track approved, the request stays IN_REVIEW.
        touch(change_request)

    product["last_review_at"] = now()
    touch(product)
    return envelope.ok(change_request_out(change_request))


def _approval_join(change_request, target, product):
    """The four-hop pin / supersede / invalidate / release cascade (PRD 3.5)."""
    # ---- hop 1: pin
    change_request["state"] = "APPROVED"
    change_request["decided_at"] = now()
    touch(change_request)
    if target is not None:
        target["state"] = "PINNED"
        touch(target)
    listing = calc.find_listing(change_request["product_id"], change_request["retailer_id"])
    previous_id = None
    if listing is not None:
        previous_id = listing.get("pinned_content_version_id")
        listing["pinned_content_version_id"] = target["id"] if target is not None else None
        touch(listing)
    product["last_pinned_at"] = now()
    product["status"] = "ACTIVE"

    # ---- hop 2: supersede the revision the listing previously pinned
    previous = None
    if previous_id and target is not None and previous_id != target["id"]:
        previous = db.content_versions.get(previous_id)
        if previous is not None:
            previous["state"] = "SUPERSEDED"
            touch(previous)
            recompute.recompute_pin_count(previous)

    # ---- hop 3: invalidate QUEUED jobs on the superseded revision
    touched_listings = []
    if previous is not None:
        for job in in_order([j for j in db.jobs.values()
                             if j["content_version_id"] == previous["id"]
                             and j["state"] == "QUEUED"]):
            job["state"] = "INVALIDATED"
            touch(job)
            # ---- hop 4: each invalidated job releases its slots
            job_listing = db.listings.get(job["retailer_listing_id"])
            if job_listing is not None:
                retailer = db.retailers.get(job_listing["retailer_id"])
                if retailer is not None:
                    recompute.bump_retailer_ledger(retailer)
                if job_listing["id"] not in touched_listings:
                    touched_listings.append(job_listing["id"])
        for listing_id in touched_listings:
            job_listing = db.listings[listing_id]
            recompute.recompute_listing_blocking(job_listing)
            holding = [j for j in calc.jobs_of_listing(listing_id)
                       if j["state"] in calc.HOLDING_JOB_STATES]
            if not holding and int(job_listing["open_blocking_error_count"]) == 0:
                recompute.set_syndication_state(job_listing, "NOT_SYNDICATED")
            recompute.recompute_listing_readiness(job_listing)

    # ---- alongside the hops: scores, the pin ledger and product health
    if listing is not None:
        recompute.recompute_listing_completeness(listing)
    if target is not None:
        recompute.recompute_pin_count(target)
    recompute.recompute_product_health(product)
