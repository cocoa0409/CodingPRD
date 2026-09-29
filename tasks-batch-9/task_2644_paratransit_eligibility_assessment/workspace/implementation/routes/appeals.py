"""PRD 3.8 — appeals, independent review and the four-hop remedy cascade."""

from flask import Blueprint

import lookups
import mirrors
import owners
import serializers
import shapes
from auth import actor_id, require
from envelope import created, ok
from errors import ApiError
from routes.determinations import _create_auto_referral, _signed_off_assessment
from store import base_record, date_of, db, now, plus_days, touch

bp = Blueprint("appeals", __name__)

APPEAL_FILING_WINDOW_DAYS = 60
APPEAL_DECISION_WINDOW_DAYS = 30


def _scoring_assessment_of(determination):
    """The assessment that produced the scores behind the contested grant."""
    app_rec = db.applications.get(determination["application_id"])
    if app_rec is None:
        return None
    return _signed_off_assessment(app_rec)


# ---------------------------------------------------------------------------
# POST /appeals
# ---------------------------------------------------------------------------

@bp.post("/appeals")
@require(("Applicant", "AccessibilityOfficeAdmin"), ownership=owners.determination_body)
def file_appeal():
    payload = shapes.body()
    determination = None
    if payload.get("determination_id") is not None:
        determination = lookups.determination(payload["determination_id"])
    if determination is None:
        shapes.req_str(payload, "determination_id")
    grounds = shapes.req_str(payload, "grounds")
    request_hearing = shapes.opt_bool(payload, "request_hearing", False)

    if determination["status"] != "ISSUED":
        raise ApiError("ERR_DETERMINATION_NOT_APPEALABLE")

    filed_at = now()
    deadline = plus_days(determination["effective_date"], APPEAL_FILING_WINDOW_DAYS)
    if date_of(filed_at) > deadline:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")

    rec = base_record()
    rec.update(
        {
            "determination_id": determination["id"],
            "grounds": grounds,
            "request_hearing": request_hearing,
            "filed_at": filed_at,
            "filing_deadline_date": deadline,
            "status": "FILED",
            "reviewer_user_id": None,
            "hearing_at": None,
            "heard_at": None,
            "decision_due_date": None,
            "outcome": None,
            "granted_category": None,
            "decided_at": None,
            "decision_note": None,
            "continued_service_extended": False,
        }
    )
    db.appeals[rec["id"]] = rec

    determination["under_appeal"] = True
    touch(determination)
    applicant = db.applicants.get(determination["applicant_id"])
    if applicant is not None:
        touch(applicant)
    return created(serializers.appeal(rec))


# ---------------------------------------------------------------------------
# POST /appeals/{id}/assign-reviewer
# ---------------------------------------------------------------------------

@bp.post("/appeals/<appeal_id>/assign-reviewer")
@require(("AccessibilityOfficeAdmin",), identity_required=True)
def assign_reviewer(appeal_id):
    rec = lookups.appeal(appeal_id)
    payload = shapes.body()
    reviewer_user_id = shapes.req_str(payload, "reviewer_user_id")

    if rec["status"] != "FILED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")

    determination = db.determinations.get(rec["determination_id"])
    if determination is not None:
        if reviewer_user_id == determination["determined_by_user_id"]:
            raise ApiError("ERR_REVIEWER_NOT_INDEPENDENT")
        assessment = _scoring_assessment_of(determination)
        if assessment is not None and reviewer_user_id == assessment["scored_by_user_id"]:
            raise ApiError("ERR_REVIEWER_NOT_INDEPENDENT")

    rec["reviewer_user_id"] = reviewer_user_id
    rec["status"] = "REVIEWER_ASSIGNED"
    touch(rec)
    return ok(serializers.appeal(rec))


# ---------------------------------------------------------------------------
# POST /appeals/{id}/hearing
# ---------------------------------------------------------------------------

@bp.post("/appeals/<appeal_id>/hearing")
@require(("IndependentReviewer",), assigned_reviewer=True)
def open_review(appeal_id):
    rec = lookups.appeal(appeal_id)
    payload = shapes.body()
    hearing_at = shapes.opt_instant(payload, "hearing_at", None)
    if hearing_at is not None and not hearing_at > now():
        shapes.bad("hearing_at must be strictly later than the current instant.")

    if rec["status"] != "REVIEWER_ASSIGNED":
        raise ApiError("ERR_APPEAL_STATE_INVALID")

    if rec["request_hearing"]:
        if hearing_at is None:
            raise ApiError("ERR_HEARING_REQUIRED")
        rec["hearing_at"] = hearing_at
        rec["status"] = "HEARING_SCHEDULED"
    else:
        if hearing_at is not None:
            raise ApiError("ERR_HEARING_NOT_REQUESTED")
        heard_at = now()
        rec["heard_at"] = heard_at
        rec["decision_due_date"] = plus_days(date_of(heard_at), APPEAL_DECISION_WINDOW_DAYS)
        rec["status"] = "HEARD"
    touch(rec)
    return ok(serializers.appeal(rec))


# ---------------------------------------------------------------------------
# POST /appeals/{id}/decision
# ---------------------------------------------------------------------------

@bp.post("/appeals/<appeal_id>/decision")
@require(("IndependentReviewer",), identity_required=True, assigned_reviewer=True)
def record_decision(appeal_id):
    rec = lookups.appeal(appeal_id)
    payload = shapes.body()
    outcome = shapes.req_enum(payload, "outcome", shapes.APPEAL_OUTCOMES)
    granted_category = shapes.opt_enum(
        payload, "granted_category", shapes.GRANTED_CATEGORIES, None
    )
    decision_note = shapes.opt_str(payload, "decision_note", None)

    if rec["status"] != "HEARD":
        raise ApiError("ERR_APPEAL_STATE_INVALID")

    if outcome == "UPHELD":
        if granted_category is not None:
            raise ApiError("ERR_GRANTED_CATEGORY_MISMATCH")
    elif granted_category is None:
        raise ApiError("ERR_GRANTED_CATEGORY_MISMATCH")

    decided_at = now()
    rec["outcome"] = outcome
    rec["granted_category"] = granted_category
    rec["decision_note"] = decision_note
    rec["decided_at"] = decided_at
    rec["status"] = "DECIDED"
    touch(rec)

    determination = db.determinations.get(rec["determination_id"])
    applicant = None if determination is None else db.applicants.get(determination["applicant_id"])

    if outcome == "UPHELD":
        if determination is not None:
            determination["under_appeal"] = False
            touch(determination)
            if applicant is not None:
                if determination["category"] == "INELIGIBLE":
                    applicant["current_eligibility_status"] = "INELIGIBLE"
                touch(applicant)
        return ok(serializers.appeal(rec))

    # Hop 2 — the contested determination is vacated and a successor is issued.
    if determination is not None:
        determination["status"] = "VACATED"
        determination["under_appeal"] = False
        touch(determination)

        successor = base_record()
        successor.update(
            {
                "application_id": determination["application_id"],
                "applicant_id": determination["applicant_id"],
                "category": granted_category,
                "status": "ISSUED",
                "effective_date": date_of(decided_at),
                "term_days": mirrors.term_days_for(granted_category),
                "expires_at": mirrors.expires_at_for(granted_category, date_of(decided_at)),
                "rationale": decision_note,
                "determined_by_user_id": rec["reviewer_user_id"],
                "issued_at": decided_at,
                "under_appeal": False,
                "origin": "APPEAL_REMEDY",
                # PRD 3.8: trip conditions are NOT copied onto the successor.
                "trip_condition_count": 0,
                "fixed_route_competency_confirmed": serializers.competency_confirmed(
                    determination["applicant_id"]
                ),
            }
        )
        db.determinations[successor["id"]] = successor

        # Hop 3 — the rider's eligibility mirrors follow the successor.
        if applicant is not None:
            mirrors.set_eligibility(applicant, "ELIGIBLE", granted_category, successor["id"])

        # Hop 4 — a CONDITIONAL remedy auto-refers the rider to travel training.
        if granted_category == "CONDITIONAL":
            _create_auto_referral(successor)

    return ok(serializers.appeal(rec))
