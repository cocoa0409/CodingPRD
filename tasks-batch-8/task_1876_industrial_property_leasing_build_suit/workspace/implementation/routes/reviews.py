"""Environmental & zoning-use compliance reviews (PRD §3.4) with the
FLAGGED -> IN_REVIEW remediation loop.
"""
from flask import Blueprint

from db import store, new_entity, public, touch
from errors import ApiError, ERR_INVALID_STATE, ERR_DUPLICATE_REVIEW
from middleware import (
    authenticate, body, require_fields, check_enums, get_fk, get_path,
    REVIEW_TYPES, OUTCOMES, ALL_ROLES,
)
from response import success_object
from routes import list_response

bp = Blueprint("reviews", __name__)


@bp.post("/api/compliance-reviews")
def create_review():
    authenticate(["ComplianceOfficer"])
    b = body()
    # Priority 4 (existence), input-list order: site_id then requirement_id.
    site = get_fk(b, "site_id", store.sites)
    req = get_fk(b, "requirement_id", store.requirements)
    require_fields(b, [
        ("site_id", "string", True),
        ("requirement_id", "string", True),
        ("review_type", "string", True),
        ("findings", "string", False),
    ])
    if site is None:
        site = store.sites[b["site_id"]]
    if req is None:
        req = store.requirements[b["requirement_id"]]
    check_enums(b, [("review_type", REVIEW_TYPES)])
    # Priority 14/19: uniqueness per (site_id, requirement_id, review_type).
    dupe = any(
        r["site_id"] == site["id"] and r["requirement_id"] == req["id"]
        and r["review_type"] == b["review_type"]
        for r in store.reviews.values())
    if dupe:
        raise ApiError(ERR_DUPLICATE_REVIEW,
                       "A review with this (site_id, requirement_id, review_type) already exists", 409)
    ent = new_entity({
        "site_id": site["id"],
        "requirement_id": req["id"],
        "review_type": b["review_type"],
        "findings": b.get("findings"),
        "status": "PENDING",
    })
    store.reviews[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/api/compliance-reviews")
def list_reviews():
    authenticate(ALL_ROLES)
    return list_response(store.reviews.values(), [
        ("site_id", lambda e: e["site_id"]),
        ("requirement_id", lambda e: e["requirement_id"]),
        ("review_type", lambda e: e["review_type"]),
        ("status", lambda e: e["status"]),
    ])


@bp.get("/api/compliance-reviews/<rid>")
def get_review(rid):
    authenticate(ALL_ROLES)
    return success_object(public(get_path(store.reviews, rid, "compliance review")))


@bp.post("/api/compliance-reviews/<rid>/begin")
def begin_review(rid):
    authenticate(["ComplianceOfficer"])
    rev = get_path(store.reviews, rid, "compliance review")
    if rev["status"] not in ("PENDING", "FLAGGED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot begin a review in status {rev['status']}", 409)
    rev["status"] = "IN_REVIEW"
    touch(rev)
    return success_object(public(rev))


@bp.post("/api/compliance-reviews/<rid>/resolve")
def resolve_review(rid):
    authenticate(["ComplianceOfficer"])
    rev = get_path(store.reviews, rid, "compliance review")
    b = body()
    require_fields(b, [
        ("outcome", "string", True),
        ("findings", "string", False),
    ])
    check_enums(b, [("outcome", OUTCOMES)])
    if rev["status"] != "IN_REVIEW":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot resolve a review in status {rev['status']}", 409)
    rev["status"] = b["outcome"]
    if b.get("findings") is not None:
        rev["findings"] = b["findings"]
    touch(rev)
    return success_object(public(rev))
