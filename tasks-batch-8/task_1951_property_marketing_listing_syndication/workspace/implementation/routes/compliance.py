from flask import Blueprint

import clock
from db import store
from errors import ApiError, ERR_REVIEW_DECIDED
from middleware import (
    authenticate, require_roles, get_body, f_str, f_enum, f_str_list,
    not_found, paginate,
)
from response import success_object, success_list
from services.ops import touch, lifecycle_transition
from services.serialize import review_json

bp = Blueprint("compliance", __name__)

READ_ROLES = ("ListingAgent", "MarketingCoordinator", "ComplianceOfficer",
              "MarketingDirector")


@bp.route("/listings/<listing_id>/compliance-reviews", methods=["GET"])
def list_reviews(listing_id):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    if listing_id not in store.listings:
        raise not_found("Listing not found")
    items = sorted(
        (r for r in store.reviews.values() if r["listing_id"] == listing_id),
        key=lambda r: (r["created_at"], r["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([review_json(r) for r in page], limit, offset, total)


@bp.route("/compliance-reviews/<review_id>/decision", methods=["POST"])
def decide(review_id):
    _, role = authenticate()
    require_roles(role, ("ComplianceOfficer",))
    review = store.reviews.get(review_id)
    if review is None:
        raise not_found("ComplianceReview not found")
    body = get_body()
    outcome = f_enum(body, "outcome", ("APPROVED", "REJECTED"), required=True)
    flagged_terms = f_str_list(body, "flagged_terms")
    notes = f_str(body, "notes")
    if review["status"] != "PENDING":
        raise ApiError(ERR_REVIEW_DECIDED, 409,
                       "Compliance review has already been decided")
    now = clock.now()
    review["status"] = outcome
    review["decided_at"] = now
    review["notes"] = notes
    if outcome == "REJECTED":
        review["flagged_terms"] = flagged_terms
    touch(review, now)
    if outcome == "REJECTED":
        listing = store.listings.get(review["listing_id"])
        if listing is not None and listing["lifecycle_status"] == "PENDING_REVIEW":
            # PENDING_REVIEW -> COMPLIANCE_HOLD cascade (PRD 3.3).
            lifecycle_transition(listing, "COMPLIANCE_HOLD", now,
                                 terminal=False, queue_terminal_sync=False)
    return success_object(review_json(review))
