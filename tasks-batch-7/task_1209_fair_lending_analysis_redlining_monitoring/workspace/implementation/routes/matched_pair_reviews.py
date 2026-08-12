"""Matched-pair reviews."""
from flask import Blueprint, g, request

import db
from errors import already_terminal, err, invalid_state
from middleware import (
    body, check_enum, get_or_404, list_page, occ_check, require_field, require_roles,
)
from response import success_list, success_obj
from services.cap import pair_comparable, select_control

bp = Blueprint("matched_pair_reviews", __name__)

ROLES = ("LoanOfficer", "FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")
OPEN_STATES = ("PENDING", "INITIAL_REVIEWED", "DISPUTED")
OUTCOMES = ("COMPARABLE_TREATMENT", "DIFFERENTIAL_TREATMENT")


@bp.post("/fair-lending/matched-pair-reviews")
@require_roles("FairLendingAnalyst")
def create_review():
    data = body()
    finding_id = require_field(data, "finding_id")
    target_id = require_field(data, "target_application_id")
    control_id = data.get("control_application_id")
    finding = get_or_404("findings", finding_id, "DisparityFinding")
    target = get_or_404("applications", target_id, "Application")
    control = None
    if control_id is not None:
        control = get_or_404("applications", control_id, "Application")
    # OCC on the parent finding version.
    occ_check(data, "expected_finding_version", finding["version"])
    if finding["status"] != "UNDER_REVIEW":
        raise invalid_state("Matched-pair reviews require a finding UNDER_REVIEW")
    selector_used = False
    if control is None:
        # Target must still be a protected-group DENIED application for the
        # selector contract to make sense.
        control = select_control(target)
        if control is None:
            raise err(
                "ERR_EMPTY_CONTROL_POOL",
                "No eligible CONTROL comparator for the target application",
            )
        selector_used = True
        if not pair_comparable(target, control):
            raise err("ERR_MATCH_NOT_COMPARABLE", "Matched pair is not comparable")
    else:
        if not pair_comparable(target, control):
            raise err("ERR_MATCH_NOT_COMPARABLE", "Matched pair is not comparable")
    # Supersede the finding's currently open review.
    for r in db.STORES["reviews"].values():
        if r["finding_id"] == finding["id"] and r["status"] in OPEN_STATES:
            r["status"] = "SUPERSEDED"
            db.touch(r)
    rec = db.new_record(
        {
            "finding_id": finding["id"],
            "target_application_id": target["id"],
            "control_application_id": control["id"],
            "selector_used": selector_used,
            "status": "PENDING",
            "initial_outcome": None,
            "initial_reviewer_user_id": None,
            "confirmed_by_user_id": None,
            "dispute_reason": None,
        }
    )
    db.STORES["reviews"][rec["id"]] = rec
    # Serialization point: the finding's version advances.
    db.touch(finding)
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/matched-pair-reviews")
@require_roles(*ROLES)
def list_reviews():
    page, total, limit, offset = list_page(
        "reviews",
        {
            "finding_id": request.args.get("finding_id"),
            "target_application_id": request.args.get("target_application_id"),
            "control_application_id": request.args.get("control_application_id"),
            "status": request.args.get("status"),
        },
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/matched-pair-reviews/<reviewId>")
@require_roles(*ROLES)
def get_review(reviewId):
    rec = get_or_404("reviews", reviewId, "MatchedPairReview")
    return success_obj(db.public(rec))


def _load(reviewId):
    rec = get_or_404("reviews", reviewId, "MatchedPairReview")
    if rec["status"] in ("CONFIRMED", "SUPERSEDED"):
        raise already_terminal("MatchedPairReview is in terminal state %s" % rec["status"])
    return rec


@bp.post("/fair-lending/matched-pair-reviews/<reviewId>/submit-initial")
@require_roles("FairLendingAnalyst")
def submit_initial(reviewId):
    rec = _load(reviewId)
    if rec["status"] not in ("PENDING", "DISPUTED"):
        raise invalid_state("Review is not awaiting initial submission")
    data = body()
    outcome = check_enum(require_field(data, "outcome"), OUTCOMES, "outcome")
    rec["status"] = "INITIAL_REVIEWED"
    rec["initial_outcome"] = outcome
    rec["initial_reviewer_user_id"] = g.user_id
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/matched-pair-reviews/<reviewId>/confirm")
@require_roles("FairLendingOfficer")
def confirm(reviewId):
    rec = get_or_404("reviews", reviewId, "MatchedPairReview")
    # SoD (identity-level, priority 3): confirmer must differ from the
    # initial reviewer.
    if (
        rec.get("initial_reviewer_user_id") is not None
        and rec["initial_reviewer_user_id"] == g.user_id
    ):
        raise err(
            "ERR_SOD_VIOLATION",
            "Confirming officer must differ from the initial reviewer",
        )
    if rec["status"] in ("CONFIRMED", "SUPERSEDED"):
        raise already_terminal("MatchedPairReview is in terminal state %s" % rec["status"])
    if rec["status"] != "INITIAL_REVIEWED":
        raise invalid_state("Review is not INITIAL_REVIEWED")
    rec["status"] = "CONFIRMED"
    rec["confirmed_by_user_id"] = g.user_id
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/matched-pair-reviews/<reviewId>/dispute")
@require_roles("LoanOfficer")
def dispute(reviewId):
    rec = get_or_404("reviews", reviewId, "MatchedPairReview")
    target = db.STORES["applications"].get(rec["target_application_id"])
    # Ownership: the disputing officer must own the target application.
    if target is None:
        raise err("ERR_NOT_FOUND", "Application does not exist")
    if g.user_id != target["loan_officer_id"]:
        raise err(
            "ERR_OWNERSHIP_MISMATCH",
            "Only the target application's loan officer may dispute",
        )
    if rec["status"] in ("CONFIRMED", "SUPERSEDED"):
        raise already_terminal("MatchedPairReview is in terminal state %s" % rec["status"])
    if rec["status"] != "INITIAL_REVIEWED":
        raise invalid_state("Review is not INITIAL_REVIEWED")
    data = body()
    rec["status"] = "DISPUTED"
    rec["dispute_reason"] = data.get("reason")
    db.touch(rec)
    return success_obj(db.public(rec))
