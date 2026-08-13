from flask import Blueprint

import errors
from db import DB, CLOCK, new_id, stamp_new, touch, iso_now
from middleware import (
    get_context, require_role, get_json_body, require_fields, reject_unexpected,
    require_string, require_int, require_enum,
)
from response import success_object
from services import bids as bid_svc

bp = Blueprint("recommendations", __name__)

ESTIMATORS = {"LeadEstimator", "ChiefEstimator", "PrequalReviewer"}


def serialize_recommendation(rec):
    return {
        "id": rec["id"],
        "bid_package_id": rec["bid_package_id"],
        "recommended_bid_id": rec["recommended_bid_id"],
        "rationale": rec["rationale"],
        "created_by_user_id": rec["created_by_user_id"],
        "decision_notes": rec["decision_notes"],
        "decided_by_user_id": rec["decided_by_user_id"],
        "decided_at": rec["decided_at"],
        "status": rec["status"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def get_rec_or_404(rec_id):
    rec = DB.recommendations.get(rec_id)
    if rec is None:
        raise errors.err_resource_not_found()
    return rec


@bp.post("/award-recommendations")
def create_recommendation():
    user_id, role = get_context()
    require_role(role, {"LeadEstimator"})
    body = get_json_body()
    reject_unexpected(body, {
        "bid_package_id", "recommended_bid_id", "rationale", "expected_bid_package_version",
    })
    require_fields(body, [
        "bid_package_id", "recommended_bid_id", "rationale", "expected_bid_package_version",
    ])
    pkg_id = body["bid_package_id"]
    bid_id = body["recommended_bid_id"]
    if not isinstance(pkg_id, str) or not isinstance(bid_id, str):
        raise errors.err_invalid_request("bid_package_id and recommended_bid_id must be strings")
    # Existence: body FKs in input order — bid_package_id, then recommended_bid_id
    pkg = DB.bid_packages.get(pkg_id)
    if pkg is None:
        raise errors.err_package_not_found()
    bid = DB.bids.get(bid_id)
    if bid is None:
        raise errors.err_bid_not_found()
    rationale = require_string(body, "rationale")
    expected = require_int(body, "expected_bid_package_version")

    if pkg["status"] != "TABULATED":
        raise errors.err_package_invalid_state("Recommendation create requires TABULATED")
    if bid["bid_package_id"] != pkg_id or bid["status"] != "SUBMITTED":
        raise errors.err_recommended_bid_ineligible()
    active = any(
        r["bid_package_id"] == pkg_id and r["status"] in ("DRAFT", "SUBMITTED")
        for r in DB.recommendations.values()
    )
    if active:
        raise errors.err_active_recommendation()
    if expected != pkg["version"]:
        raise errors.err_stale_package_version()

    rec = {
        "id": new_id(),
        "bid_package_id": pkg_id,
        "recommended_bid_id": bid_id,
        "rationale": rationale,
        "created_by_user_id": user_id,
        "decision_notes": None,
        "decided_by_user_id": None,
        "decided_at": None,
        "status": "DRAFT",
    }
    stamp_new(rec)
    rec["_created_at_dt"] = CLOCK.now()
    DB.recommendations[rec["id"]] = rec
    touch(pkg)  # creating a draft increments BidPackage.version by 1
    return success_object(serialize_recommendation(rec), 201)


@bp.get("/award-recommendations/<rec_id>")
def read_recommendation(rec_id):
    _, role = get_context()
    require_role(role, ESTIMATORS)
    rec = get_rec_or_404(rec_id)
    return success_object(serialize_recommendation(rec))


@bp.post("/award-recommendations/<rec_id>/submit")
def submit_recommendation(rec_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    rec = get_rec_or_404(rec_id)
    if rec["status"] != "DRAFT":
        raise errors.err_invalid_resource_state("Submit requires DRAFT")
    pkg = DB.bid_packages.get(rec["bid_package_id"])
    if pkg is None or pkg["status"] != "TABULATED":
        raise errors.err_package_invalid_state("Submit requires package TABULATED")
    rec["status"] = "SUBMITTED"
    touch(rec)
    # Package TABULATED -> RECOMMENDATION_PENDING (leveling locks)
    pkg["status"] = "RECOMMENDATION_PENDING"
    touch(pkg)
    return success_object(serialize_recommendation(rec))


@bp.post("/award-recommendations/<rec_id>/decide")
def decide_recommendation(rec_id):
    user_id, role = get_context()
    require_role(role, {"ChiefEstimator"})
    rec = get_rec_or_404(rec_id)
    body = get_json_body()
    reject_unexpected(body, {"decision", "decision_notes"})
    require_fields(body, ["decision"])
    decision = require_enum(body, "decision", {"APPROVED", "RETURNED"})
    notes = body.get("decision_notes")
    if notes is not None and not isinstance(notes, str):
        raise errors.err_invalid_request("decision_notes must be a string")

    if rec["status"] != "SUBMITTED":
        raise errors.err_invalid_resource_state("Decide requires SUBMITTED")
    # Segregation of duties: decider must differ from drafter
    if user_id == rec["created_by_user_id"]:
        raise errors.err_sod()
    if decision == "RETURNED" and not notes:
        raise errors.err_invalid_request("decision_notes is required when decision = RETURNED")

    rec["decided_by_user_id"] = user_id
    rec["decided_at"] = iso_now()
    rec["decision_notes"] = notes
    pkg = DB.bid_packages.get(rec["bid_package_id"])

    if decision == "APPROVED":
        rec["status"] = "APPROVED"
        touch(rec)
        # Award cascade: package -> AWARDED; recommended bid -> AWARDED;
        # every other SUBMITTED bid -> NOT_AWARDED with a feedback DRAFT.
        pkg["status"] = "AWARDED"
        touch(pkg)
        rank_by_bid = pkg.get("_leveled_rank_by_bid", {})
        amount_by_bid = pkg.get("_leveled_amount_by_bid", {})
        winning_bid = DB.bids.get(rec["recommended_bid_id"])
        winning_leveled = (
            amount_by_bid.get(winning_bid["id"])
            if winning_bid is not None else None
        )
        if winning_leveled is None and winning_bid is not None:
            winning_leveled = bid_svc.leveled_amount(winning_bid)
        for bid in list(DB.bids.values()):
            if bid["bid_package_id"] != pkg["id"] or bid["status"] != "SUBMITTED":
                continue
            if bid["id"] == rec["recommended_bid_id"]:
                bid["status"] = "AWARDED"
                touch(bid)
            else:
                bid["status"] = "NOT_AWARDED"
                touch(bid)
                fb = {
                    "id": new_id(),
                    "bid_id": bid["id"],
                    "leveled_rank": rank_by_bid.get(bid["id"]),
                    "leveled_amount_cents": amount_by_bid.get(
                        bid["id"], bid_svc.leveled_amount(bid)),
                    "winning_leveled_amount_cents": winning_leveled,
                    "notes": None,
                    "sent_at": None,
                    "status": "DRAFT",
                }
                stamp_new(fb)
                fb["_created_at_dt"] = CLOCK.now()
                DB.feedbacks[fb["id"]] = fb
    else:  # RETURNED
        rec["status"] = "RETURNED"
        touch(rec)
        # Package RECOMMENDATION_PENDING -> TABULATED (leveling unlocks)
        pkg["status"] = "TABULATED"
        touch(pkg)
    return success_object(serialize_recommendation(rec))
