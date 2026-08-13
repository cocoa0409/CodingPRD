"""IntakeAssessment endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_RISK_BAND_VIOLATION,
    ERR_COUNSELOR_OVER_CAPACITY,
    ERR_NO_CRISIS_COVERAGE,
    ERR_UNAUTHORIZED,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    optional_string,
    paginate,
    parse_pagination,
    require_bool,
    require_int,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("intakes", __name__)


@bp.route("/ucc/intake-assessments", methods=["POST"])
@require_roles("TriageScreener")
def create_intake(_user_id: str, _role: str):
    body = get_json_body()
    # Existence: path ids before body FKs; here only body FKs.
    student_id = require_string(body, "student_id")
    screener_id = require_string(body, "screener_id")
    phq9 = require_int(body, "phq9_score", minimum=0, maximum=27)
    gad7 = require_int(body, "gad7_score", minimum=0, maximum=21)
    ideation_flag = require_bool(body, "ideation_flag")
    recent_attempt_flag = require_bool(body, "recent_attempt_flag")

    # FK resolution
    student = db.students.get(student_id)
    if student is None:
        raise_err(ERR_NOT_FOUND, "student_id does not resolve")
    screener = db.counselors.get(screener_id)
    if screener is None:
        raise_err(ERR_NOT_FOUND, "screener_id does not resolve")

    points, band = domain.compute_risk(phq9, gad7, ideation_flag, recent_attempt_flag)
    assessment = {
        "student_id": student_id,
        "screener_id": screener_id,
        "phq9_score": phq9,
        "gad7_score": gad7,
        "ideation_flag": ideation_flag,
        "recent_attempt_flag": recent_attempt_flag,
        "risk_points": points,
        "risk_band": band,
        "disposition": "PENDING",
    }
    db.stamp_new_light(assessment)
    db.intake_assessments[assessment["id"]] = assessment

    # Risk re-banding side effect (group removal on CRITICAL).
    domain.on_new_intake_assessment(student_id, assessment)
    return success_object(serialize(assessment), 201)


@bp.route("/ucc/intake-assessments/<assessment_id>", methods=["GET"])
@require_roles("TriageScreener", "Counselor", "ClinicalDirector")
def get_intake(assessment_id: str, _user_id: str, _role: str):
    a = db.intake_assessments.get(assessment_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, "IntakeAssessment id does not exist")
    return success_object(serialize(a))


@bp.route("/ucc/intake-assessments", methods=["GET"])
@require_roles("TriageScreener", "Counselor", "ClinicalDirector")
def list_intakes(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.intake_assessments.values()))
    items = apply_filters(items, ["student_id", "screener_id", "risk_band"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/ucc/intake-assessments/<assessment_id>/complete", methods=["POST"])
@require_roles("TriageScreener")
def complete_intake(assessment_id: str, _user_id: str, _role: str):
    a = db.intake_assessments.get(assessment_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, "IntakeAssessment id does not exist")
    body = get_json_body()

    if a.get("disposition") != "PENDING":
        raise_err(ERR_INVALID_STATE, "IntakeAssessment already has a disposition")

    risk_band = a.get("risk_band")
    student = db.students.get(a.get("student_id"))
    if student is None:
        raise_err(ERR_NOT_FOUND, "Student no longer exists")

    if risk_band in ("LOW", "MODERATE"):
        # Route: SHORT_TERM_CARE
        # Enrollment status gate
        if student.get("enrollment_status") != "ENROLLED":
            raise_err(ERR_INVALID_STATE, "Student enrollment_status must be ENROLLED")
        primary_counselor_id = require_string(body, "primary_counselor_id")
        counselor = db.counselors.get(primary_counselor_id)
        if counselor is None:
            raise_err(ERR_NOT_FOUND, "primary_counselor_id does not resolve")
        if not counselor.get("active", True):
            raise_err(ERR_INVALID_STATE, "primary_counselor is not active")

        # academic_term: payload, default to currently published policy's term.
        academic_term = optional_string(body, "academic_term")
        if academic_term is None or academic_term == "":
            published = domain.any_published_policy()
            if published is not None:
                academic_term = published.get("academic_term")
        if academic_term is None or academic_term == "":
            raise_err(ERR_INVALID_REQUEST, "academic_term required when no policy is published")

        # Intersession guard: no PUBLISHED policy for the term + LOW band ->
        # ERR_RISK_BAND_VIOLATION.
        policy_for_term = domain.published_policy_for_term(academic_term)
        if policy_for_term is None and risk_band == "LOW":
            raise_err(ERR_RISK_BAND_VIOLATION, "Intersession capacity is reserved for acute need")

        # Counselor capacity gate: caseload points.
        new_points = int(a.get("risk_points", 0))
        current_load = domain.counselor_caseload_load(primary_counselor_id)
        if current_load + new_points > int(counselor.get("max_caseload_risk_points", 0)):
            raise_err(ERR_COUNSELOR_OVER_CAPACITY, "Counselor caseload risk-point cap would be exceeded")

        # Compute session limit.
        session_limit = domain.session_limit_for_episode(
            risk_band, student.get("funding_model", "STUDENT_FEE"), academic_term
        )

        episode = {
            "student_id": student["id"],
            "primary_counselor_id": primary_counselor_id,
            "intake_assessment_id": a["id"],
            "academic_term": academic_term,
            "session_limit": session_limit,
            "sessions_consumed": 0,
            "status": "OPEN",
            "prior_episode_id": None,
            "exemption_granted": False,
        }
        db.stamp_new(episode)
        db.episodes[episode["id"]] = episode

        a["disposition"] = "SHORT_TERM_CARE"
        # The new non-terminal episode re-anchors the student's current term
        # (PRD §3.6); re-derive the strike recount and posture.
        domain.recompute_strikes_and_posture(student)
        return success_object(serialize(a))

    if risk_band == "HIGH":
        # Route: COMMUNITY_REFERRAL
        referral = {
            "student_id": student["id"],
            "episode_id": None,
            "provider_name": None,
            "required_specialty": "GEN",
            "status": "PENDING",
            "rematch_count": 0,
        }
        db.stamp_new(referral)
        db.referrals[referral["id"]] = referral
        a["disposition"] = "COMMUNITY_REFERRAL"
        return success_object(serialize(a))

    # CRITICAL -> CRISIS_PROTOCOL
    now = db.clock()
    qualifying = []
    for sh in db.crisis_shifts.values():
        if sh.get("status") != "CLAIMED":
            continue
        if sh.get("shift_kind") != "WALK_IN":
            continue
        start = db.parse_iso(sh["starts_at"])
        end = db.parse_iso(sh["ends_at"])
        if start <= now < end:
            qualifying.append(sh)
    if not qualifying:
        raise_err(ERR_NO_CRISIS_COVERAGE, "No CLAIMED WALK_IN shift covers the current logical clock")
    # Earliest starts_at, tie-break created_at ASC
    qualifying.sort(key=lambda s: (db.parse_iso(s["starts_at"]), s.get("created_at", "")))
    shift = qualifying[0]

    visit = {
        "student_id": student["id"],
        "shift_id": shift["id"],
        "presenting_risk_band": risk_band,
        "status": "QUEUED",
        "disposition": "NONE",
    }
    db.stamp_new(visit)
    db.crisis_visits[visit["id"]] = visit
    a["disposition"] = "CRISIS_PROTOCOL"
    return success_object(serialize(a))
