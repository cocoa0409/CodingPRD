"""Appeals: filing, rebuttal loop, decision cascades."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, not_found, ERR_UNAUTHORIZED,
                    ERR_PERIOD_NOT_LOCKED, ERR_APPEAL_SUBJECT_STATE,
                    ERR_APPEAL_SUBJECT_MISMATCH, ERR_APPEAL_WINDOW_EXPIRED,
                    ERR_APPEAL_INVALID_STATE, ERR_APPEAL_ROUND_LIMIT)
from middleware import (require_roles, ROLE_ACO_ADMIN, ROLE_ACTUARY,
                        ROLE_APPEALS, ROLE_PR)
from response import success, list_success
from serializers import appeal_out
from services import calc
from validate import get_json_body, validate_body

bp = Blueprint("appeals", __name__)

APPEAL_SPEC = {
    "agreement_period_id": {"type": "string", "required": True},
    "subject_type": {"type": "enum", "enum": ["ATTRIBUTION", "SETTLEMENT"],
                     "required": True},
    "subject_id": {"type": "string", "required": True},
    "grounds": {"type": "string", "required": True},
}

REBUTTAL_SPEC = {
    "memo": {"type": "string", "required": True},
}

DECIDE_SPEC = {
    "outcome": {"type": "enum", "enum": ["UPHELD", "DENIED"], "required": True},
    "rationale": {"type": "string", "required": False},
}

APPEAL_READ_ROLES = [ROLE_ACO_ADMIN, ROLE_ACTUARY, ROLE_APPEALS, ROLE_PR]

APPEAL_WINDOW_DAYS = 30


@bp.post("/aco/appeals")
def create_appeal():
    uid, _ = require_roles([ROLE_PR])
    body = validate_body(get_json_body(), APPEAL_SPEC)
    period = db.periods.get(body["agreement_period_id"])
    if period is None:
        raise not_found("Agreement period not found")
    # subject_id is polymorphic (not a foreign key) but must resolve.
    if body["subject_type"] == "ATTRIBUTION":
        subject = db.attribution_records.get(body["subject_id"])
        if subject is None:
            raise not_found("Attribution record not found")
    else:
        subject = db.settlements.get(body["subject_id"])
        if subject is None:
            raise not_found("Settlement not found")
    # Period posture (priority 6): ATTRIBUTION appeals need ASSIGNMENT_LOCKED.
    if body["subject_type"] == "ATTRIBUTION" and period["status"] != "ASSIGNMENT_LOCKED":
        raise ApiError(ERR_PERIOD_NOT_LOCKED, 409,
                       "Attribution appeals require an ASSIGNMENT_LOCKED period")
    # Subject appealable state (priority 7).
    if body["subject_type"] == "ATTRIBUTION":
        if subject["status"] != "FINAL":
            raise ApiError(ERR_APPEAL_SUBJECT_STATE, 409,
                           "Attribution appeals require a FINAL record")
    else:
        if subject["status"] != "FINAL":
            raise ApiError(ERR_APPEAL_SUBJECT_STATE, 409,
                           "Settlement appeals require a FINAL settlement")
    # Filing window (priority 11): within 30 days of finalized_at, logical clock.
    if body["subject_type"] == "SETTLEMENT":
        finalized = subject.get("finalized_at_dt")
        if finalized is not None and db.logical_now() > finalized + timedelta(
                days=APPEAL_WINDOW_DAYS):
            raise ApiError(ERR_APPEAL_WINDOW_EXPIRED, 422,
                           "Settlement appeal filed more than 30 days after "
                           "finalized_at")
    # Cross-entity ownership (priority 12).
    if subject["agreement_period_id"] != period["id"]:
        raise ApiError(ERR_APPEAL_SUBJECT_MISMATCH, 422,
                       "Appeal subject does not belong to the given "
                       "agreement_period_id")
    appeal = db.stamp_new({
        "id": db.new_id(),
        "agreement_period_id": period["id"],
        "subject_type": body["subject_type"],
        "subject_id": body["subject_id"],
        "filed_by_participant_id": uid,
        "grounds": body["grounds"],
        "round_count": 0,
        "decided_outcome": None,
        "status": "UNDER_REVIEW",
    })
    db.appeals[appeal["id"]] = appeal
    # A successful attribution filing moves the record FINAL -> UNDER_APPEAL.
    if body["subject_type"] == "ATTRIBUTION":
        subject["status"] = "UNDER_APPEAL"
        db.bump(subject)
    return success(appeal_out(appeal), 201)


def _get_appeal_or_404(appeal_id):
    appeal = db.appeals.get(appeal_id)
    if appeal is None:
        raise not_found("Appeal not found")
    return appeal


@bp.get("/aco/appeals/<appeal_id>")
def get_appeal(appeal_id):
    uid, role = require_roles(APPEAL_READ_ROLES)
    appeal = _get_appeal_or_404(appeal_id)
    if role == ROLE_PR and appeal["filed_by_participant_id"] != uid:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "Appeal belongs to another participant")
    return success(appeal_out(appeal))


@bp.get("/aco/appeals")
def list_appeals():
    uid, role = require_roles(APPEAL_READ_ROLES)
    items = list(db.appeals.values())
    for param in ("agreement_period_id", "filed_by_participant_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [a for a in items if a[param] == value]
    if role == ROLE_PR:
        items = [a for a in items if a["filed_by_participant_id"] == uid]
    items.sort(key=lambda a: a["created_at"])
    return list_success([appeal_out(a) for a in items])


@bp.post("/aco/appeals/<appeal_id>/rebuttals")
def file_rebuttal(appeal_id):
    uid, _ = require_roles([ROLE_PR])
    appeal = _get_appeal_or_404(appeal_id)
    # Only the filer may rebut (authorization, priority 2).
    if uid != appeal["filed_by_participant_id"]:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "Only the filing participant may rebut this appeal")
    validate_body(get_json_body(), REBUTTAL_SPEC)
    if appeal["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_APPEAL_INVALID_STATE, 409,
                       "Rebuttals require the appeal to be UNDER_REVIEW")
    if appeal["round_count"] >= 2:
        raise ApiError(ERR_APPEAL_ROUND_LIMIT, 422,
                       "Rebuttal round cap of 2 reached")
    appeal["round_count"] += 1
    appeal["status"] = "REBUTTAL"
    db.bump(appeal)
    return success(appeal_out(appeal))


@bp.post("/aco/appeals/<appeal_id>/resume-review")
def resume_review(appeal_id):
    require_roles([ROLE_APPEALS])
    get_json_body()
    appeal = _get_appeal_or_404(appeal_id)
    if appeal["status"] != "REBUTTAL":
        raise ApiError(ERR_APPEAL_INVALID_STATE, 409,
                       "Resume-review requires the appeal to be in REBUTTAL")
    appeal["status"] = "UNDER_REVIEW"
    db.bump(appeal)
    return success(appeal_out(appeal))


@bp.post("/aco/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    require_roles([ROLE_APPEALS])
    body = validate_body(get_json_body(), DECIDE_SPEC)
    appeal = _get_appeal_or_404(appeal_id)
    if appeal["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_APPEAL_INVALID_STATE, 409,
                       "Decide requires the appeal to be UNDER_REVIEW")
    outcome = body["outcome"]
    appeal["decided_outcome"] = outcome
    appeal["status"] = outcome
    db.bump(appeal)

    if appeal["subject_type"] == "ATTRIBUTION":
        record = db.attribution_records.get(appeal["subject_id"])
        if record is not None and record["status"] == "UNDER_APPEAL":
            if outcome == "UPHELD":
                record["status"] = "OVERTURNED"
                db.bump(record)
                calc.stale_proposed_settlements(appeal["agreement_period_id"])
            else:  # DENIED returns the record to FINAL
                record["status"] = "FINAL"
                db.bump(record)
    else:  # SETTLEMENT subject
        if outcome == "UPHELD":
            settlement = db.settlements.get(appeal["subject_id"])
            # Exactly as a manual reopen: recompute + void PENDING/APPROVED.
            if settlement is not None and settlement["status"] == "FINAL":
                calc.reopen_settlement(settlement)
        # DENIED leaves the settlement untouched.
    return success(appeal_out(appeal))
