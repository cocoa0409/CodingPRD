"""Committee roster, reviews, votes, and chair ratification."""

from flask import Blueprint

from db import db
from errors import (
    ApiError, not_found, invalid_state, already_terminal, stale_version,
)
from middleware import require_roles, ALL_API_ROLES
from response import ok_object
from services import (
    new_record, touch, sync_market, decided_outcome, ser_member, ser_review,
    ser_vote,
)
from util import get_body, req_str, req_enum, req_int, opt_bool, list_response

bp = Blueprint("committee", __name__)

_BALLOTS = ("APPROVE", "REJECT", "ABSTAIN")


# ---------------------------------------------------------------------------
# Committee members
# ---------------------------------------------------------------------------

@bp.post("/api/committee-members")
def create_member():
    require_roles("PlatformAdmin")
    body = get_body(required=True)
    name = req_str(body, "display_name")
    is_chair = opt_bool(body, "is_chair", default=False)
    if is_chair:
        for m in db.members.values():
            if m["is_chair"] and m["member_status"] == "ACTIVE":
                raise ApiError(
                    "ERR_CHAIR_CONFLICT", 409,
                    "An ACTIVE chair already exists")
    rec = new_record()
    rec.update({
        "display_name": name,
        "is_chair": is_chair,
        "member_status": "ACTIVE",
    })
    db.members[rec["id"]] = rec
    return ok_object(ser_member(rec), status=201)


@bp.get("/api/committee-members")
def list_members():
    require_roles(*ALL_API_ROLES)
    return list_response(db.members.values(), ser_member,
                         filters=["member_status"])


@bp.get("/api/committee-members/<mid>")
def get_member(mid):
    require_roles(*ALL_API_ROLES)
    rec = db.members.get(mid)
    if rec is None:
        raise not_found(f"CommitteeMember not found: {mid}")
    return ok_object(ser_member(rec))


@bp.post("/api/committee-members/<mid>/deactivate")
def deactivate_member(mid):
    require_roles("PlatformAdmin")
    rec = db.members.get(mid)
    if rec is None:
        raise not_found(f"CommitteeMember not found: {mid}")
    if rec["member_status"] == "INACTIVE":
        raise already_terminal("CommitteeMember is INACTIVE")
    rec["member_status"] = "INACTIVE"
    touch(rec)
    return ok_object(ser_member(rec))


# ---------------------------------------------------------------------------
# Committee reviews
# ---------------------------------------------------------------------------

def _get_review(rid):
    rec = db.reviews.get(rid)
    if rec is None:
        raise not_found(f"CommitteeReview not found: {rid}")
    return rec


@bp.get("/api/committee-reviews")
def list_reviews():
    require_roles(*ALL_API_ROLES)
    return list_response(
        db.reviews.values(), ser_review,
        filters=["site_id", "sales_forecast_id", "sponsor_member_id",
                 "review_status"])


@bp.get("/api/committee-reviews/<rid>")
def get_review(rid):
    require_roles(*ALL_API_ROLES)
    return ok_object(ser_review(_get_review(rid)))


@bp.post("/api/committee-reviews/<rid>/votes")
def cast_vote(rid):
    uid, _role = require_roles("CommitteeMember", "CommitteeChair")
    review = _get_review(rid)
    body = get_body(required=True)
    ballot = req_enum(body, "ballot", _BALLOTS)
    expected = req_int(body, "expected_review_version")
    # Layer 4: OCC guard before state checks.
    if expected != review["version"]:
        raise stale_version(
            f"expected_review_version {expected} != review version "
            f"{review['version']}")
    # Layer 5: terminal lockdown, then state permission (only OPEN votes).
    if review["review_status"] in ("RATIFIED", "EXPIRED", "VOID"):
        raise already_terminal(
            f"CommitteeReview is {review['review_status']}")
    if review["review_status"] != "OPEN":
        raise invalid_state(
            f"Review in {review['review_status']} does not accept ballots")
    # Layer 6: segregation of duties, then voter eligibility.
    if uid == review["sponsor_member_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403,
            "The review sponsor may not vote on their own review")
    member = db.members.get(uid)
    if member is None or member["member_status"] != "ACTIVE":
        raise ApiError(
            "ERR_VOTER_INELIGIBLE", 403,
            "Casting identity is not an ACTIVE committee member")
    # Layer 7: one vote per (review, member).
    for v in db.votes.values():
        if v["review_id"] == rid and v["member_id"] == uid:
            raise ApiError(
                "ERR_DUPLICATE_VOTE", 409,
                "This member has already voted on this review")
    ts = new_record()
    vote = {
        "id": ts["id"],
        "created_at": ts["created_at"],
        "created_at_sort": ts["created_at_sort"],
        "_seq": ts["_seq"],
        "review_id": rid,
        "member_id": uid,
        "ballot": ballot,
    }
    db.votes[vote["id"]] = vote
    if ballot == "APPROVE":
        review["approve_votes"] += 1
    elif ballot == "REJECT":
        review["reject_votes"] += 1
    else:
        review["abstain_votes"] += 1
    touch(review)  # every recorded ballot advances the review version by 1
    cast = (review["approve_votes"] + review["reject_votes"]
            + review["abstain_votes"])
    if cast == review["eligible_member_count"]:
        review["review_status"] = "DECIDED"
        review["decided_outcome"] = decided_outcome(
            review["approve_votes"], review["reject_votes"],
            review["abstain_votes"], review["quorum_count"])
    return ok_object(ser_vote(vote), status=201)


@bp.post("/api/committee-reviews/<rid>/ratify")
def ratify_review(rid):
    uid, _role = require_roles("CommitteeChair")
    review = _get_review(rid)
    if review["review_status"] in ("RATIFIED", "EXPIRED", "VOID"):
        raise already_terminal(
            f"CommitteeReview is {review['review_status']}")
    if review["review_status"] != "DECIDED":
        raise invalid_state(
            f"Review in {review['review_status']} cannot be ratified")
    # Layer 6: chair authority, then segregation of duties.
    member = db.members.get(uid)
    if (member is None or member["member_status"] != "ACTIVE"
            or not member["is_chair"]):
        raise ApiError(
            "ERR_NOT_CHAIR", 403,
            "Ratify requires an ACTIVE committee chair")
    if uid == review["sponsor_member_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403,
            "The review sponsor may not ratify their own review")
    review["review_status"] = "RATIFIED"
    touch(review)
    site = db.sites[review["site_id"]]
    if review["decided_outcome"] == "APPROVE":
        site["site_status"] = "APPROVED"
        touch(site)
        # Commit capital exactly once via the ledger recompute.
        sync_market(db.markets[site["market_id"]])
    else:
        site["site_status"] = "REJECTED"
        touch(site)
    return ok_object(ser_review(review))


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------

@bp.get("/api/votes")
def list_votes():
    require_roles(*ALL_API_ROLES)
    return list_response(db.votes.values(), ser_vote,
                         filters=["review_id", "member_id"])


@bp.get("/api/votes/<vid>")
def get_vote(vid):
    require_roles(*ALL_API_ROLES)
    rec = db.votes.get(vid)
    if rec is None:
        raise not_found(f"Vote not found: {vid}")
    return ok_object(ser_vote(rec))
