"""Candidates and lateral partner questionnaires."""

import cascades
import listing
import lookups as lk
import middleware as mw
import services as svc
from db import db, new_row, pub, set_fields
from errors import ApiError
from flask import Blueprint
from response import object_response

bp = Blueprint("candidates", __name__, url_prefix="/lateral-hiring")

READ_CANDIDATE = mw.READ_ALL + ("Candidate",)
OUTSTANDING = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED")


@bp.post("/candidates")
def create_candidate():
    mw.authenticate(("RecruitingCoordinator",))
    data = mw.body()
    group = None
    engagement = None
    if isinstance(data.get("target_practice_group_id"), str):
        group = lk.get_practice_group(data["target_practice_group_id"])
    if isinstance(data.get("sourcing_engagement_id"), str):
        engagement = lk.get_engagement(data["sourcing_engagement_id"])

    full_name = mw.v_str(data, "full_name", 1, 120)
    prior_firm_name = mw.v_str(data, "prior_firm_name", 1, 120)
    mw.v_str(data, "target_practice_group_id", 1, None)
    mw.v_str(data, "sourcing_engagement_id", 1, None)
    sponsor_user_id = mw.v_str(data, "sponsor_user_id", 1, 64)
    current_rate = mw.v_num(data, "current_standard_rate_usd", minimum=0,
                            exclusive_min=True)
    notice_period_days = mw.v_int(data, "notice_period_days", minimum=0, maximum=365)
    non_solicit_days = mw.v_int(data, "non_solicit_days", minimum=0, maximum=730)
    approach_confidential = mw.v_bool(data, "approach_confidential",
                                      required=False, default=True)

    if engagement["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_INVALID_STATE")
    if group["status"] != "OPEN":
        raise ApiError("ERR_PRACTICE_GROUP_FROZEN")

    row = new_row({
        "full_name": full_name,
        "prior_firm_name": prior_firm_name,
        "target_practice_group_id": group["id"],
        "sourcing_engagement_id": engagement["id"],
        "sponsor_user_id": sponsor_user_id,
        "current_standard_rate_usd": current_rate,
        "notice_period_days": notice_period_days,
        "non_solicit_days": non_solicit_days,
        "approach_confidential": approach_confidential,
        "pipeline_status": "SOURCED",
        "clearance_status": "NOT_STARTED",
        "resignation_date": None,
        "earliest_start_date": None,
        "hire_date": None,
        "open_offer_id": None,
    })
    db.candidates[row["id"]] = row
    return object_response(pub(row), 201)


@bp.get("/candidates/<candidate_id>")
def read_candidate(candidate_id):
    mw.authenticate(READ_CANDIDATE)
    return object_response(pub(lk.get_candidate(candidate_id)))


@bp.get("/candidates")
def list_candidates():
    mw.authenticate(mw.READ_ALL)
    rows = list(db.candidates.values())
    rows = listing.eq_filter(rows, "target_practice_group_id")
    rows = listing.eq_filter(rows, "sourcing_engagement_id")
    rows = listing.eq_filter(rows, "pipeline_status")
    rows = listing.eq_filter(rows, "clearance_status")
    return listing.paged(rows)


@bp.post("/candidates/<candidate_id>/approach")
def approach_candidate(candidate_id):
    mw.authenticate(("RecruitingCoordinator",))
    candidate = lk.get_candidate(candidate_id)
    if candidate["pipeline_status"] != "SOURCED":
        raise ApiError("ERR_CANDIDATE_INVALID_STATE")
    engagement = db.engagements.get(candidate["sourcing_engagement_id"])
    if engagement is None or engagement["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_INVALID_STATE")
    clock = db.clock
    if not (engagement["exclusivity_start_date"] <= clock
            < engagement["exclusivity_end_date"]):
        raise ApiError("ERR_ENGAGEMENT_INVALID_STATE")
    set_fields(candidate, pipeline_status="APPROACHED")
    return object_response(pub(candidate))


@bp.post("/candidates/<candidate_id>/withdraw")
def withdraw_candidate_route(candidate_id):
    mw.authenticate(("RecruitingCoordinator",))
    candidate = lk.get_candidate(candidate_id)
    data = mw.body()
    mw.v_str(data, "withdrawal_reason", 1, None)
    if candidate["pipeline_status"] in ("HIRED", "DECLINED", "WITHDRAWN"):
        raise ApiError("ERR_CANDIDATE_INVALID_STATE")
    cascades.withdraw_candidate(candidate)
    return object_response(pub(candidate))


# ------------------------------------------------------------- questionnaires

@bp.post("/candidates/<candidate_id>/questionnaires")
def create_questionnaire(candidate_id):
    mw.authenticate(("RecruitingCoordinator",))
    candidate = lk.get_candidate(candidate_id)
    data = mw.body()
    billings = mw.v_num(data, "declared_prior_year_billings_usd", minimum=0)
    collections = mw.v_num(data, "declared_prior_year_collections_usd", minimum=0)
    realization = mw.v_num(data, "declared_realization_rate", minimum=0,
                           maximum=1, exclusive_min=True)
    matter_types = mw.v_str_list(data, "primary_matter_types", 1, 10, 1, 60)
    if collections > billings:
        raise mw.bad("declared_prior_year_collections_usd",
                     "must not exceed declared_prior_year_billings_usd")

    if candidate["pipeline_status"] != "APPROACHED":
        raise ApiError("ERR_CANDIDATE_INVALID_STATE")
    for existing in lk.questionnaires_of_candidate(candidate_id):
        if existing["status"] not in ("ACCEPTED", "ABANDONED"):
            raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE")
    engagement = db.engagements.get(candidate["sourcing_engagement_id"])
    if engagement is None or engagement["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_INVALID_STATE")

    row = new_row({
        "candidate_id": candidate["id"],
        "status": "DRAFT",
        "revision_round": 0,
        "declared_prior_year_billings_usd": billings,
        "declared_prior_year_collections_usd": collections,
        "declared_realization_rate": realization,
        "primary_matter_types": matter_types,
        "entry_count": 0,
        "latest_assessment_id": None,
    })
    db.questionnaires[row["id"]] = row
    set_fields(candidate, pipeline_status="DILIGENCE")
    return object_response(pub(row), 201)


@bp.get("/questionnaires/<questionnaire_id>")
def read_questionnaire(questionnaire_id):
    mw.authenticate(READ_CANDIDATE)
    return object_response(pub(lk.get_questionnaire(questionnaire_id)))


@bp.get("/questionnaires")
def list_questionnaires():
    mw.authenticate(mw.READ_ALL)
    rows = list(db.questionnaires.values())
    rows = listing.eq_filter(rows, "candidate_id")
    rows = listing.eq_filter(rows, "status")
    return listing.paged(rows)


@bp.post("/questionnaires/<questionnaire_id>/submit")
def submit_questionnaire(questionnaire_id):
    user_id, _role = mw.authenticate(("Candidate",))
    questionnaire = lk.get_questionnaire(questionnaire_id)
    if user_id != questionnaire["candidate_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if questionnaire["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE")
    candidate = db.candidates.get(questionnaire["candidate_id"])
    engagement = None
    if candidate is not None:
        engagement = db.engagements.get(candidate["sourcing_engagement_id"])
    if engagement is None or engagement["status"] != "ACTIVE":
        raise ApiError("ERR_ENGAGEMENT_INVALID_STATE")
    svc.sync_questionnaire_entry_count(questionnaire)
    if questionnaire["entry_count"] < 1:
        raise ApiError("ERR_EMPTY_CLIENT_BOOK")
    set_fields(questionnaire, status="SUBMITTED")
    return object_response(pub(questionnaire))


@bp.post("/questionnaires/<questionnaire_id>/start-review")
def start_review(questionnaire_id):
    mw.authenticate(("RecruitingCoordinator",))
    questionnaire = lk.get_questionnaire(questionnaire_id)
    if questionnaire["status"] != "SUBMITTED":
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE")
    set_fields(questionnaire, status="UNDER_REVIEW")
    return object_response(pub(questionnaire))


@bp.post("/questionnaires/<questionnaire_id>/request-revision")
def request_revision(questionnaire_id):
    mw.authenticate(("RecruitingCoordinator",))
    questionnaire = lk.get_questionnaire(questionnaire_id)
    data = mw.body()
    mw.v_str(data, "revision_note", 1, None)
    if questionnaire["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE")
    if questionnaire["revision_round"] >= 3:
        raise ApiError("ERR_REVISION_LIMIT_EXCEEDED")
    set_fields(questionnaire, status="REVISION_REQUESTED",
               revision_round=questionnaire["revision_round"] + 1)
    return object_response(pub(questionnaire))


@bp.post("/questionnaires/<questionnaire_id>/accept")
def accept_questionnaire(questionnaire_id):
    mw.authenticate(("RecruitingCoordinator",))
    questionnaire = lk.get_questionnaire(questionnaire_id)
    if questionnaire["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE")
    current = [a for a in lk.assessments_of_questionnaire(questionnaire_id)
               if a["status"] == "CURRENT"]
    if not current:
        raise ApiError("ERR_QUESTIONNAIRE_INVALID_STATE",
                       "No CURRENT portability assessment exists on this questionnaire.")
    set_fields(questionnaire, status="ACCEPTED")
    return object_response(pub(questionnaire))
