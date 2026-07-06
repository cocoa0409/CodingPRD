"""ARCRequest + ARCReview: create, submit (cyclic), review, finalize."""

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now_iso, sweep_time_transitions
from entities import bump, new_arc_request, new_arc_review, new_work_order
from errors import raise_error
from response import success
from services import calc
from services import property as property_svc
from utils import (paginate, require_enum, require_fields, require_int,
                   require_str, optional_str, require_json)

bp = Blueprint("arc", __name__)


# ---------------- Create ARC request ---------------- #

@bp.route("/arc-requests", methods=["POST"])
@require_role("Homeowner")
def create_arc_request():
    body = require_json(request)
    require_fields(body, "property_id", "submitter_homeowner_id", "category", "description")
    property_id = require_str(body, "property_id")
    submitter_id = require_str(body, "submitter_homeowner_id")
    category = require_enum(body, "category", {"SIMPLE", "MEDIUM", "COMPLEX"})
    description = require_str(body, "description", allow_empty=True)

    prop = db.properties.get(property_id)
    if not prop:
        raise_error("ERR_FK_NOT_FOUND", "property_id does not resolve")
    home = db.homeowners.get(submitter_id)
    if not home:
        raise_error("ERR_FK_NOT_FOUND", "submitter_homeowner_id does not resolve")

    now_iso = get_now_iso()
    row = new_arc_request(property_id, submitter_id, category, description, now_iso)
    db.arc_requests[row["id"]] = row
    return success(row, status=201)


# ---------------- Get ARC request ---------------- #

@bp.route("/arc-requests/<rid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def get_arc_request(rid):
    r = db.arc_requests.get(rid)
    if not r:
        raise_error("ERR_NOT_FOUND", "arc request not found")
    return success(r)


# ---------------- Submit / resubmit ---------------- #

@bp.route("/arc-requests/<rid>/submit", methods=["POST"])
@require_role("Homeowner")
def submit_arc_request(rid):
    require_json(request)
    sweep_time_transitions()
    r = db.arc_requests.get(rid)
    if not r:
        raise_error("ERR_NOT_FOUND", "arc request not found")

    if r["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise_error("ERR_INVALID_STATE", "arc request not in DRAFT or REVISION_REQUESTED")

    prop = db.properties.get(r["property_id"])
    home = db.homeowners.get(r["submitter_homeowner_id"])
    # Ensure derived fields are current.
    now_iso = get_now_iso()
    if prop:
        property_svc.recompute(prop, now_iso)

    # Priority 7 gate: Property.compliance_flag != SUSPENDED.
    if prop and prop.get("compliance_flag") == "SUSPENDED":
        raise_error("ERR_PROPERTY_SUSPENDED", "property is SUSPENDED")

    # Priority 15 gate: Homeowner.standing != DELINQUENT.
    if home and home.get("standing") == "DELINQUENT":
        raise_error("ERR_HOMEOWNER_DELINQUENT", "homeowner is DELINQUENT")

    if r["status"] == "REVISION_REQUESTED":
        # Priority 16: revision_count < 3.
        if r["revision_count"] >= 3:
            raise_error("ERR_REVISION_LIMIT", "revision_count has reached 3")
        # Archive prior reviews on this request.
        for rev in db.arc_reviews.values():
            if rev["arc_request_id"] == rid:
                rev["archived"] = True

    r["status"] = "SUBMITTED"
    bump(r, now_iso)
    return success(r)


# ---------------- Submit a review ---------------- #

@bp.route("/arc-requests/<rid>/reviews", methods=["POST"])
@require_role("BoardMember")
def submit_review(rid):
    body = require_json(request)
    # Malformed-payload check first (400) — priority sequence per PRD §2.8.
    require_fields(body, "reviewer_homeowner_id", "weight", "verdict")
    reviewer_id = require_str(body, "reviewer_homeowner_id")
    weight = require_int(body, "weight", minimum=1, maximum=5)
    verdict = require_enum(body, "verdict", {"APPROVE", "REJECT", "REVISE"})
    comment = optional_str(body, "comment", default=None)

    r = db.arc_requests.get(rid)
    if not r:
        raise_error("ERR_NOT_FOUND", "arc request not found")

    reviewer = db.homeowners.get(reviewer_id)
    if not reviewer:
        raise_error("ERR_FK_NOT_FOUND", "reviewer_homeowner_id does not resolve")

    if r["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise_error("ERR_INVALID_STATE", "arc request not in SUBMITTED or UNDER_REVIEW")

    if not reviewer.get("is_board_member"):
        raise_error("ERR_REVIEWER_NOT_BOARD", "reviewer is not a board member")

    now_iso = get_now_iso()
    review = new_arc_review(
        arc_request_id=rid,
        reviewer_homeowner_id=reviewer_id,
        weight=weight,
        verdict=verdict,
        comment=comment,
        revision_count=r["revision_count"],
        now_iso=now_iso,
    )
    db.arc_reviews[review["id"]] = review

    # First review on a SUBMITTED request auto-transitions to UNDER_REVIEW.
    if r["status"] == "SUBMITTED":
        r["status"] = "UNDER_REVIEW"
        bump(r, now_iso)

    return success(review, status=201)


# ---------------- List reviews ---------------- #

@bp.route("/arc-requests/<rid>/reviews", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_reviews(rid):
    if rid not in db.arc_requests:
        raise_error("ERR_NOT_FOUND", "arc request not found")
    items = [r for r in db.arc_reviews.values() if r["arc_request_id"] == rid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)


# ---------------- Finalize ---------------- #

@bp.route("/arc-requests/<rid>/finalize", methods=["POST"])
@require_role("BoardMember")
def finalize(rid):
    require_json(request)
    r = db.arc_requests.get(rid)
    if not r:
        raise_error("ERR_NOT_FOUND", "arc request not found")
    if r["status"] != "UNDER_REVIEW":
        raise_error("ERR_INVALID_STATE", "arc request not UNDER_REVIEW")

    now_iso = get_now_iso()
    current_rev = r["revision_count"]
    current_reviews = [
        rv for rv in db.arc_reviews.values()
        if rv["arc_request_id"] == rid and rv["revision_count"] == current_rev and not rv.get("archived", False)
    ]

    verdicts = [rv["verdict"] for rv in current_reviews]

    if "REJECT" in verdicts:
        # Stamp fee, transition to REJECTED.
        fee = calc.arc_finalization_fee(r["category"], current_reviews)
        r["fee_cents"] = fee
        r["status"] = "REJECTED"
        bump(r, now_iso)
    elif "REVISE" in verdicts:
        # Increment revision_count; transition to REVISION_REQUESTED. No fee.
        r["revision_count"] = current_rev + 1
        r["status"] = "REVISION_REQUESTED"
        bump(r, now_iso)
    else:
        # All APPROVE — approve cascade.
        fee = calc.arc_finalization_fee(r["category"], current_reviews)
        r["fee_cents"] = fee
        r["status"] = "APPROVED"
        bump(r, now_iso)

        # Cascade: Property.compliance_flag -> APPROVED_MOD.
        prop = db.properties.get(r["property_id"])
        if prop:
            prop["compliance_flag"] = "APPROVED_MOD"
            bump(prop, now_iso)

        # Cascade: auto-create WorkOrder with source=AUTO_ARC.
        wo = new_work_order(
            title="Post-approval inspection",
            cost_estimate_cents=0,
            related_property_id=r["property_id"],
            source="AUTO_ARC",
            now_iso=now_iso,
        )
        db.work_orders[wo["id"]] = wo

    return success(r)
