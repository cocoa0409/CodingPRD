"""Facility compliance reviews (PRD §3.9)."""

from decimal import Decimal

from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from db import store
from errors import ApiError
from queryargs import enum_arg, matches, str_arg
from response import envelope, paged, pagination_params
from services import (REVIEW_METHODS, by_seq, qualifies_under, recompute_facility, require,
                      review_cohort, stamp_new, touch)
from util import Body, iso, pct2, serialize

bp = Blueprint("reviews", __name__)

REVIEW_STATUSES = ("DRAFT", "COMPUTED", "STALE", "CERTIFIED")


@bp.post("/compliance-reviews")
def create_review():
    user_id, _ = authenticate(("ComplianceOfficer",))
    body = Body(request.get_json(silent=True))

    facility_id = body.id_field("facility_id")
    expected_version = body.int_field("expected_facility_version", minimum=0)
    method = body.enum_field("method", REVIEW_METHODS)
    period_start = body.date_field("period_start")
    period_end = body.date_field("period_end")

    # ladder rank 8 — period ordering
    if period_end < period_start:
        raise ApiError("ERR_INVALID_PERIOD")

    # ladder rank 10 — body identifier existence
    facility = require(store.facilities, facility_id)

    # ladder rank 15 — optimistic concurrency on the facility
    if expected_version != facility["version"]:
        raise ApiError("ERR_STALE_FACILITY_VERSION")

    review = stamp_new({
        "facility_id": facility_id,
        "method": method,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "created_by_user_id": user_id,
        "certified_by_user_id": None,
        "total_cases": 0,
        "qualifying_cases": 0,
        "compliance_pct": None,
        "outcome": None,
        "computed_at": None,
        "certified_at": None,
        "stale_reason": None,
        "status": "DRAFT",
    })
    store.reviews[review["id"]] = review

    # opening a review is itself version-advancing (PRD §2.7)
    touch(facility)

    return envelope(serialize(review), 201)


@bp.get("/compliance-reviews/<review_id>")
def get_review(review_id):
    authenticate(ALL_ROLES)
    review = require(store.reviews, review_id)
    return envelope(serialize(review), 200)


@bp.get("/compliance-reviews")
def list_reviews():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    filters = {
        "facility_id": str_arg("facility_id"),
        "method": enum_arg("method", REVIEW_METHODS),
        "status": enum_arg("status", REVIEW_STATUSES),
    }
    items = [r for r in by_seq(list(store.reviews.values())) if matches(r, filters)]
    page, pagination = paged(items, limit, offset)
    return envelope([serialize(r) for r in page], 200, pagination)


@bp.post("/compliance-reviews/<review_id>/compute")
def compute_review(review_id):
    authenticate(("ComplianceOfficer",))
    review = require(store.reviews, review_id)

    # ladder rank 16 — declared from DRAFT and from STALE
    if review["status"] not in ("DRAFT", "STALE"):
        raise ApiError("ERR_INVALID_STATE")

    cohort = review_cohort(review)

    # ladder rank 47 — an empty cohort is refused outright
    if not cohort:
        raise ApiError("ERR_EMPTY_COMPLIANCE_COHORT")

    facility = store.facilities.get(review["facility_id"])
    qualifying = sum(1 for admission in cohort if qualifies_under(review, admission))
    compliance_pct = pct2(qualifying, len(cohort))
    threshold = Decimal(str(facility["compliance_threshold_pct"])) if facility else Decimal("0")

    review["total_cases"] = len(cohort)
    review["qualifying_cases"] = qualifying
    review["compliance_pct"] = compliance_pct
    review["outcome"] = "PASS" if Decimal(str(compliance_pct)) >= threshold else "FAIL"
    review["computed_at"] = iso(store.clock)
    review["stale_reason"] = None
    review["status"] = "COMPUTED"
    touch(review)

    return envelope(serialize(review), 200)


@bp.post("/compliance-reviews/<review_id>/certify")
def certify_review(review_id):
    user_id, _ = authenticate(("ComplianceOfficer",))
    review = require(store.reviews, review_id)

    # ladder rank 14 — segregation of duties
    if user_id == review["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # ladder rank 16 — declared transition COMPUTED -> CERTIFIED
    if review["status"] != "COMPUTED":
        raise ApiError("ERR_INVALID_STATE")

    cohort = review_cohort(review)

    # ladder rank 48 — no cohort member may be fiscally reopened
    for admission in cohort:
        if admission["payment_status"] == "REOPENED":
            raise ApiError("ERR_COHORT_PAYMENT_UNSETTLED")

    review["status"] = "CERTIFIED"
    review["certified_at"] = iso(store.clock)
    review["certified_by_user_id"] = user_id
    touch(review)

    facility = store.facilities.get(review["facility_id"])
    if facility is not None:
        facility["certified_compliance_pct"] = review["compliance_pct"]
        facility["_certified_source_review_id"] = review["id"]
        # PRD §2.8: posture is re-derived after every certification, and the
        # provisional cohort figures are recomputed alongside it.  §3.9 states
        # the facility's version increases by 1, so the bump is unconditional.
        recompute_facility(facility, force_touch=True)

    return envelope(serialize(review), 200)
