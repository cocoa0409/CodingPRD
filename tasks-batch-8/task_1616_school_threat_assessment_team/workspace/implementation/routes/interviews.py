"""Interview endpoints (PRD section 3.3)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_CASE_NOT_UNDER_ASSESSMENT,
    ERR_INTERVIEW_NOT_SCHEDULED,
    ERR_INTERVIEW_OVERLAP,
    ERR_INVALID_TIME_RANGE,
    ERR_MAX_INTERVIEWS_EXCEEDED,
    ERR_NOT_FOUND,
    ERR_SUBJECT_INTERVIEW_TOO_EARLY,
)
from middleware import require_roles
from response import success_object
from services import domain
from util import (
    get_json_body,
    parse_iso8601,
    require_enum,
    require_int,
    require_string,
    require_ts,
)

bp = Blueprint("interviews", __name__)

INTERVIEWEE_TYPES = {"SUBJECT", "WITNESS", "PARENT", "REPORTER"}


def _get_interview_or_404(interview_id: str) -> dict:
    interview = db.interviews.get(interview_id)
    if interview is None:
        raise_err(ERR_NOT_FOUND, "Interview id does not exist")
    return interview


@bp.route("/interviews", methods=["POST"])
@require_roles("ThreatAssessor")
def create_interview(_user_id: str, _role: str):
    body = get_json_body()
    case_id = require_string(body, "case_id")
    interviewee_type = require_enum(body, "interviewee_type", INTERVIEWEE_TYPES)
    starts_at = require_ts(body, "starts_at")
    ends_at = require_ts(body, "ends_at")

    # Body-FK existence, then referenced-case state.
    case = domain.get_case_or_404(case_id)
    if case["status"] != "UNDER_ASSESSMENT":
        raise_err(ERR_CASE_NOT_UNDER_ASSESSMENT,
                  "Interview scheduling requires status UNDER_ASSESSMENT")

    case_interviews = domain.case_children(db.interviews, case["id"])

    # Business safety: a SUBJECT interview requires a COMPLETED non-SUBJECT one.
    if interviewee_type == "SUBJECT":
        has_completed_non_subject = any(
            iv["status"] == "COMPLETED" and iv["interviewee_type"] != "SUBJECT"
            for iv in case_interviews
        )
        if not has_completed_non_subject:
            raise_err(ERR_SUBJECT_INTERVIEW_TOO_EARLY,
                      "SUBJECT interview requires a COMPLETED non-SUBJECT interview")

    # Quota: at most 8 non-CANCELLED interviews per case.
    non_cancelled = [iv for iv in case_interviews if iv["status"] != "CANCELLED"]
    if len(non_cancelled) >= domain.MAX_INTERVIEWS_PER_CASE:
        raise_err(ERR_MAX_INTERVIEWS_EXCEEDED,
                  "Case already has 8 non-CANCELLED interviews")

    # Temporal: non-degenerate window, then half-open overlap vs SCHEDULED.
    start_dt = parse_iso8601(starts_at, "starts_at")
    end_dt = parse_iso8601(ends_at, "ends_at")
    if not end_dt > start_dt:
        raise_err(ERR_INVALID_TIME_RANGE, "ends_at must be strictly after starts_at")
    for iv in case_interviews:
        if iv["status"] != "SCHEDULED":
            continue
        ex_start = parse_iso8601(iv["starts_at"], "starts_at")
        ex_end = parse_iso8601(iv["ends_at"], "ends_at")
        if start_dt < ex_end and ex_start < end_dt:
            raise_err(ERR_INTERVIEW_OVERLAP,
                      "Interview overlaps an existing SCHEDULED interview for the case")

    interview = {
        "case_id": case["id"],
        "interviewee_type": interviewee_type,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
        "findings_score": None,
        "summary": None,
        "completed_at": None,
    }
    db.stamp_new(interview)
    db.interviews[interview["id"]] = interview
    return success_object(db.public(interview), 201)


@bp.route("/interviews/<interview_id>/complete", methods=["POST"])
@require_roles("ThreatAssessor")
def complete_interview(interview_id: str, _user_id: str, _role: str):
    body = get_json_body()
    findings_score = require_int(body, "findings_score", minimum=0, maximum=10)
    summary = require_string(body, "summary")

    interview = _get_interview_or_404(interview_id)
    if interview["status"] != "SCHEDULED":
        raise_err(ERR_INTERVIEW_NOT_SCHEDULED,
                  "Complete requires interview status SCHEDULED")

    interview["status"] = "COMPLETED"
    interview["findings_score"] = findings_score
    interview["summary"] = summary
    interview["completed_at"] = db.now_logical_iso()
    db.touch(interview)
    return success_object(db.public(interview))


@bp.route("/interviews/<interview_id>/cancel", methods=["POST"])
@require_roles("ThreatAssessor")
def cancel_interview(interview_id: str, _user_id: str, _role: str):
    interview = _get_interview_or_404(interview_id)
    if interview["status"] != "SCHEDULED":
        raise_err(ERR_INTERVIEW_NOT_SCHEDULED,
                  "Cancel requires interview status SCHEDULED")

    interview["status"] = "CANCELLED"
    db.touch(interview)
    return success_object(db.public(interview))
