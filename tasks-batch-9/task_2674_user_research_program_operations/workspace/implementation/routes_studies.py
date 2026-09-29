"""Studies: opening, the moderator guide, fielding and invitations (PRD 3.3, 3.4)."""
from datetime import timedelta

from flask import Blueprint, g

import serializers
from auth import ALL_ROLES, require_roles
from calc import (
    POOL_MAX_CONCURRENT_FIELDING,
    auto_invite_candidates,
    recompute_participant,
    set_field,
    study_metrics,
    study_recruitments,
)
from clock import clock
from envelope import array_response, created, ok, paged_listing
from errors import ApiError
from invites import create_recruitment
from store import by_created, db
from validators import (
    body,
    exact_object,
    filter_enum,
    participant_or_404,
    pool_or_404,
    ref,
    req_datetime,
    req_enum,
    req_int,
    req_str,
    request_or_404,
    study_or_404,
)

bp = Blueprint("studies", __name__)

METHODS = ("INTERVIEW", "USABILITY_TEST", "DIARY_STUDY", "SURVEY")
EXECUTION_STATUSES = ("PLANNED", "GUIDE_APPROVED", "FIELDING", "ANALYSIS", "REPORTED", "CLOSED")
RECRUITMENT_STATUSES = ("NOT_STARTED", "RECRUITING", "QUOTA_MET", "RECRUITMENT_FAILED")
CRITERIA_SPEC = {
    "required_segment": "string",
    "required_locale": "string",
    "target_answers": "string[]",
    "disqualifying_answers": "string[]",
}
ANSWERS_SPEC = {"segment": "string", "locale": "string", "answers": "string[]"}


@bp.post("/studies")
@require_roles("Researcher", "ResearchLead")
def create_study():
    data = body()
    research_request = request_or_404(ref(data, "research_request_id"))
    pool = pool_or_404(ref(data, "participant_pool_id"))
    req_str(data, "research_request_id")
    req_str(data, "participant_pool_id")
    method = req_enum(data, "method", METHODS)
    target = req_int(data, "target_participant_count", minimum=1)
    criteria = exact_object(data, "screening_criteria", CRITERIA_SPEC)
    amount = req_int(data, "incentive_amount_cents", minimum=0)
    fielding_start = req_datetime(data, "fielding_start")
    fielding_end = req_datetime(data, "fielding_end")
    if not fielding_end > fielding_start:
        raise ApiError("ERR_INVALID_REQUEST", "fielding_end must be strictly after fielding_start.")
    if research_request["status"] == "IN_STUDY":
        raise ApiError("ERR_INVALID_STATE", "That request already has a study.")
    if research_request["status"] != "APPROVED" or method != research_request["approved_method"]:
        raise ApiError(
            "ERR_METHOD_NOT_APPROVED",
            "The study method must equal the approved_method of an APPROVED request.",
        )
    row = db.new("studies", {
        "research_request_id": research_request["id"],
        "participant_pool_id": pool["id"],
        "lead_user_id": g.user_id,
        "method": method,
        "target_participant_count": target,
        "screening_criteria": criteria,
        "incentive_amount_cents": amount,
        "fielding_start": fielding_start,
        "fielding_end": fielding_end,
        "guide_version_label": None,
        "guide_question_count": None,
        "guide_status": "NONE",
        "guide_version_pinned": None,
        "execution_status": "PLANNED",
        "recruitment_status": "NOT_STARTED",
        "invited_count": 0,
        "screened_in_count": 0,
        "completed_count": 0,
        "fielded_at": None,
        "fielding_closed_at": None,
    })
    set_field(research_request, "status", "IN_STUDY")
    return created(serializers.study(row))


@bp.put("/studies/<study_id>/guide")
@require_roles("Researcher", "ResearchLead")
def write_guide(study_id):
    study = study_or_404(study_id)
    data = body()
    label = req_str(data, "guide_version_label")
    count = req_int(data, "guide_question_count")
    if study["execution_status"] not in ("PLANNED", "GUIDE_APPROVED"):
        raise ApiError("ERR_INVALID_STATE", "The guide cannot be rewritten from %s." % study["execution_status"])
    set_field(study, "guide_version_label", label)
    set_field(study, "guide_question_count", count)
    set_field(study, "guide_status", "DRAFT")
    set_field(study, "guide_version_pinned", None)
    return ok(serializers.study(study))


@bp.post("/studies/<study_id>/guide/approve")
@require_roles("ResearchLead")
def approve_guide(study_id):
    study = study_or_404(study_id)
    if study["execution_status"] not in ("PLANNED", "GUIDE_APPROVED"):
        raise ApiError("ERR_INVALID_STATE", "No guide approval transition exists from %s." % study["execution_status"])
    if study["guide_status"] != "DRAFT":
        raise ApiError("ERR_GUIDE_NOT_APPROVED", "Only a DRAFT guide can be approved.")
    set_field(study, "guide_status", "APPROVED")
    set_field(study, "guide_version_pinned", study["guide_version_label"])
    if study["execution_status"] == "PLANNED":
        set_field(study, "execution_status", "GUIDE_APPROVED")
    return ok(serializers.study(study))


@bp.post("/studies/<study_id>/field")
@require_roles("Researcher", "ResearchLead")
def field_study(study_id):
    study = study_or_404(study_id)
    if study["execution_status"] != "GUIDE_APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only a GUIDE_APPROVED study can be fielded.")
    if study["guide_status"] != "APPROVED":
        raise ApiError("ERR_GUIDE_NOT_APPROVED", "The moderator guide must be APPROVED.")
    decision = _governing_decision(study)
    if decision is not None and decision["status"] == "LOCKED":
        raise ApiError("ERR_DECISION_LOCKED", "The governing roadmap decision is LOCKED.")
    overlapping = 0
    for other in db.studies.values():
        if other["id"] == study["id"]:
            continue
        if other["participant_pool_id"] != study["participant_pool_id"]:
            continue
        if other["execution_status"] != "FIELDING":
            continue
        if other["fielding_start"] <= study["fielding_end"] and study["fielding_start"] <= other["fielding_end"]:
            overlapping += 1
    if overlapping >= POOL_MAX_CONCURRENT_FIELDING:
        raise ApiError("ERR_POOL_FIELDING_CAPACITY", "The pool already has two studies in the field.")
    set_field(study, "execution_status", "FIELDING")
    set_field(study, "fielded_at", clock.now())
    return ok(serializers.study(study))


@bp.post("/studies/<study_id>/close-fielding")
@require_roles("Researcher", "ResearchLead")
def close_fielding(study_id):
    study = study_or_404(study_id)
    if study["execution_status"] != "FIELDING":
        raise ApiError("ERR_INVALID_STATE", "Only a FIELDING study can close fielding.")
    if any(r["status"] == "SCHEDULED" for r in study_recruitments(study)):
        raise ApiError("ERR_INVALID_STATE", "A recruitment is still SCHEDULED.")
    set_field(study, "execution_status", "ANALYSIS")
    set_field(study, "fielding_closed_at", clock.now())
    if study["recruitment_status"] == "RECRUITING" and study["completed_count"] == 0:
        set_field(study, "recruitment_status", "RECRUITMENT_FAILED")
    elif study["recruitment_status"] == "NOT_STARTED" and study["invited_count"] == 0:
        set_field(study, "recruitment_status", "RECRUITMENT_FAILED")
    return ok(serializers.study(study))


def _governing_decision(study):
    research_request = db.requests.get(study["research_request_id"])
    if research_request is None:
        return None
    return db.decisions.get(research_request["roadmap_decision_id"])


def _recruitment_gates(study, pool):
    if study["execution_status"] != "FIELDING" or study["recruitment_status"] == "QUOTA_MET":
        raise ApiError("ERR_RECRUITMENT_CLOSED", "The study is not accepting recruitments.")
    if pool["status"] == "CLOSED":
        raise ApiError("ERR_POOL_CLOSED", "The participant pool is CLOSED.")


@bp.post("/studies/<study_id>/recruitments")
@require_roles("Researcher", "ResearchLead", "ResearchOpsAdmin")
def invite_participant(study_id):
    data = body()
    participant = participant_or_404(ref(data, "participant_id"))
    study = study_or_404(study_id)
    req_str(data, "participant_id")
    answers = exact_object(data, "screening_answers", ANSWERS_SPEC)
    pool = db.pools.get(study["participant_pool_id"])
    _recruitment_gates(study, pool)
    if any(r["participant_id"] == participant["id"] for r in study_recruitments(study)):
        raise ApiError("ERR_DUPLICATE_RECRUITMENT", "That participant is already recruited for this study.")
    if participant["status"] == "SUPPRESSED":
        raise ApiError("ERR_PARTICIPANT_SUPPRESSED", "That participant is SUPPRESSED.")
    own_pool = db.pools.get(participant["pool_id"]) or pool
    if participant["contacts_in_window"] >= own_pool["contact_cap_per_window"]:
        raise ApiError("ERR_CONTACT_CAP_EXCEEDED", "That participant has reached the contact cap.")
    row = create_recruitment(study, pool, participant, answers)
    return created(serializers.recruitment(row))


@bp.post("/studies/<study_id>/recruitments/auto-invite")
@require_roles("ResearchOpsAdmin")
def auto_invite(study_id):
    study = study_or_404(study_id)
    data = body()
    count = req_int(data, "count", minimum=1)
    pool = db.pools.get(study["participant_pool_id"])
    _recruitment_gates(study, pool)
    if pool["status"] != "OPEN":
        raise ApiError("ERR_POOL_RESTRICTED", "Batch invitation requires an OPEN pool.")
    candidates = auto_invite_candidates(study, pool)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_PARTICIPANTS", "No participant of the pool is eligible.")
    rows = []
    for participant in candidates:
        if len(rows) >= count:
            break
        try:
            rows.append(create_recruitment(study, pool, participant, None))
        except ApiError as exc:
            if exc.error_id != "ERR_INCENTIVE_BUDGET_EXCEEDED":
                raise
            break
    if not rows:
        raise ApiError(
            "ERR_INCENTIVE_BUDGET_EXCEEDED",
            "The first candidate's reservation exceeds the pool's available budget.",
        )
    return array_response([serializers.recruitment(r) for r in rows], 201)


@bp.get("/studies/<study_id>")
@require_roles(*ALL_ROLES)
def read_study(study_id):
    return ok(serializers.study(study_or_404(study_id)))


@bp.get("/studies")
@require_roles(*ALL_ROLES)
def list_studies():
    research_request = request_or_404(_arg("research_request_id"))
    pool = pool_or_404(_arg("participant_pool_id"))
    execution_status = filter_enum("execution_status", EXECUTION_STATUSES)
    recruitment_status = filter_enum("recruitment_status", RECRUITMENT_STATUSES)
    rows = list(db.studies.values())
    if research_request is not None:
        rows = [s for s in rows if s["research_request_id"] == research_request["id"]]
    if pool is not None:
        rows = [s for s in rows if s["participant_pool_id"] == pool["id"]]
    if execution_status is not None:
        rows = [s for s in rows if s["execution_status"] == execution_status]
    if recruitment_status is not None:
        rows = [s for s in rows if s["recruitment_status"] == recruitment_status]
    return paged_listing(by_created(rows), serializers.study)


def _arg(name):
    from flask import request
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


@bp.get("/studies/<study_id>/metrics")
@require_roles("Stakeholder", "Researcher", "ResearchLead", "ResearchOpsAdmin")
def read_metrics(study_id):
    study = study_or_404(study_id)
    metrics = study_metrics(study)
    metrics.pop("study_id", None)
    return ok(metrics)
