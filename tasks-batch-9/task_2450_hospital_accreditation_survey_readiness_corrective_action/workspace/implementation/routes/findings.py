"""Findings, condition-level escalation and the evidence-of-standards-compliance
response cycle (PRD 3.7, 3.8)."""

from flask import Blueprint, g

import calc
import cascade
import serialize
from auth import ALL_ROLES, require_roles
from envelope import array_response, object_response
from errors import ApiError
from helpers import (
    body,
    get_finding,
    opt_str,
    page,
    pagination,
    req_bool,
    req_enum,
    req_int,
    req_str,
)
from store import base_entity, db, rows, touch

bp = Blueprint("findings", __name__)

SUBMITTABLE_STATES = ("RESPONSE_PENDING", "CONDITION_LEVEL_ESCALATED", "CLARIFICATION_REQUESTED")


@bp.get("/accreditation/survey-findings/<finding_id>")
def read_finding(finding_id):
    require_roles(*ALL_ROLES)
    finding = get_finding(finding_id)
    return object_response(serialize.finding(finding))


@bp.post("/accreditation/survey-findings/<finding_id>/escalate")
def escalate_finding(finding_id):
    require_roles("ExternalSurveyor")
    b = body()
    req_str(b, "rationale")

    finding = get_finding(finding_id)

    # Rung 20
    if finding["state"] != "RESPONSE_PENDING":
        raise ApiError("ERR_FINDING_NOT_AWAITING_RESPONSE")

    # Rung 27
    if not finding["condition_level"]:
        raise ApiError("ERR_NOT_CONDITION_LEVEL")

    finding["state"] = "CONDITION_LEVEL_ESCALATED"
    touch(finding)

    standard = db.standards.get(finding["standard_id"])
    if standard is not None:
        cascade.mark_standard_deficient(standard)

    window = db.windows.get(finding["survey_window_id"])
    if window is not None:
        window["follow_up_required"] = True
        if window["survey_closed_at"] is not None:
            window["follow_up_due_at"] = calc.add_days(
                window["survey_closed_at"], calc.FOLLOW_UP_LEAD_DAYS
            )
        touch(window)

    return object_response(serialize.finding(finding))


@bp.post("/accreditation/survey-findings/<finding_id>/esc-submissions")
def create_esc_submission(finding_id):
    require_roles("StandardOwner")
    b = body()
    corrective_action_summary = req_str(b, "corrective_action_summary")
    measure_of_success = req_str(b, "measure_of_success")
    leadership_signoff = req_bool(b, "leadership_signoff")
    expected_finding_version = req_int(b, "expected_finding_version")

    # Rung 5
    finding = get_finding(finding_id)

    # Rung 8
    if expected_finding_version != finding["version"]:
        raise ApiError("ERR_STALE_FINDING_VERSION")

    # Rung 20
    if finding["state"] not in SUBMITTABLE_STATES:
        raise ApiError("ERR_FINDING_NOT_AWAITING_RESPONSE")

    # Rung 26
    if finding["condition_level"] and finding["state"] == "RESPONSE_PENDING":
        raise ApiError("ERR_CONDITION_LEVEL_ESCALATION_REQUIRED")

    # Rung 33
    due = finding["response_due_at"]
    if due is not None and db.clock > due:
        raise ApiError("ERR_ESC_WINDOW_CLOSED")

    # Rung 37
    if not leadership_signoff:
        raise ApiError("ERR_LEADERSHIP_SIGNOFF_REQUIRED")

    # Rung 41
    if not cascade.is_active_primary_owner(finding["standard_id"], g.user_id):
        raise ApiError("ERR_SUBMITTER_NOT_STANDARD_OWNER")

    finding["submission_count"] += 1
    submission = base_entity("EscSubmission", versioned=False)
    submission.update(
        {
            "survey_finding_id": finding["id"],
            "corrective_action_summary": corrective_action_summary,
            "measure_of_success": measure_of_success,
            "leadership_signoff": leadership_signoff,
            "submission_round": finding["submission_count"],
            "submitted_by_user_id": g.user_id,
            "decision": "PENDING",
            "decision_note": None,
        }
    )
    db.submissions[submission["id"]] = submission

    finding["state"] = "RESPONSE_SUBMITTED"
    touch(finding)

    return object_response(serialize.esc_submission(submission), 201)


@bp.get("/accreditation/survey-findings/<finding_id>/esc-submissions")
def list_esc_submissions(finding_id):
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    finding = get_finding(finding_id)
    result = [s for s in rows(db.submissions) if s["survey_finding_id"] == finding["id"]]
    items, total = page(result, limit, offset)
    return array_response([serialize.esc_submission(s) for s in items], limit, offset, total)


def _newest_submission(finding_id):
    candidates = [s for s in rows(db.submissions) if s["survey_finding_id"] == finding_id]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (s["submission_round"], s["_seq"]))


@bp.post("/accreditation/survey-findings/<finding_id>/esc-review")
def review_esc_submission(finding_id):
    require_roles("ExternalSurveyor")
    b = body()
    decision = req_enum(b, "decision", calc.REVIEW_DECISIONS)
    decision_note = opt_str(b, "decision_note")

    finding = get_finding(finding_id)

    # Rung 20
    if finding["state"] != "RESPONSE_SUBMITTED":
        raise ApiError("ERR_FINDING_NOT_AWAITING_RESPONSE")

    # Rung 36
    if (
        decision == "CLARIFICATION_REQUESTED"
        and finding["clarification_round_count"] >= calc.MAX_CLARIFICATION_ROUNDS
    ):
        raise ApiError("ERR_CLARIFICATION_LIMIT_EXCEEDED")

    submission = _newest_submission(finding["id"])
    if submission is not None:
        # PRD 2.5: writing the decision introduces no updated_at or version on
        # an EscSubmission.
        submission["decision"] = decision
        submission["decision_note"] = decision_note

    if decision == "CLARIFICATION_REQUESTED":
        finding["clarification_round_count"] += 1
        finding["state"] = "CLARIFICATION_REQUESTED"
        finding["response_due_at"] = calc.esc_due_clarification(
            db.clock, finding["initial_response_due_at"]
        )
    elif decision == "ACCEPTED":
        if finding["condition_level"]:
            finding["state"] = "FOLLOW_UP_PENDING"
        else:
            finding["state"] = "ACCEPTED"
            finding["accepted_at"] = db.clock
    else:
        finding["state"] = "RESPONSE_PENDING"
    touch(finding)

    return object_response(serialize.finding(finding))
