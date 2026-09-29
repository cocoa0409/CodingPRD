"""EnvironmentalReview endpoints (PRD section 3.8)."""

from flask import Blueprint

from db import db, new_record, now_ts, serialize
from errors import ApiError
from middleware import authenticate, get_bool, get_enum, get_str, json_body, pagination
from records import assign, touch
from response import object_response
from routes.listing import paginated
from services import domain

bp = Blueprint("environmental_reviews", __name__)

READ_ROLES = ("ProgramAdmin", "EnvironmentalReviewer", "AuditOfficer", "Subgrantee")
PATHWAYS = ("CATEGORICAL_EXCLUSION", "EA_REQUIRED", "MITIGATION_PLAN_ACCEPTED",
            "ADVERSE_EFFECT")


@bp.post("/broadband/awards/<award_id>/environmental-review")
def create_environmental_review(award_id):
    authenticate("EnvironmentalReviewer")
    body = json_body()
    tribal = get_bool(body, "tribal_consultation_required", required=False, default=False)
    shpo = get_bool(body, "shpo_consultation_required", required=False, default=False)

    award = domain.require_award(award_id)                               # priority 25
    if award["award_state"] != "OBLIGATED":                              # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")

    review = new_record({
        "award_id": award["id"],
        "ehp_state": "SCREENING",
        "pathway": None,
        "tribal_consultation_required": tribal,
        "shpo_consultation_required": shpo,
        "mitigation_summary": None,
        "cleared_by_user_id": None,
        "cleared_at": None,
    })
    db.env_reviews[review["id"]] = review
    return object_response(serialize(review), 201)


@bp.get("/broadband/awards/<award_id>/environmental-review")
def list_environmental_review(award_id):
    authenticate(*READ_ROLES)
    limit, offset = pagination()
    award = domain.require_award(award_id)
    review = domain.find_env_review(award)
    return paginated([review] if review is not None else [], limit, offset)


@bp.post("/broadband/awards/<award_id>/environmental-review/determination")
def record_determination(award_id):
    authenticate("EnvironmentalReviewer")
    body = json_body()
    pathway = get_enum(body, "pathway", PATHWAYS)
    mitigation_summary = get_str(body, "mitigation_summary", required=False)

    award = domain.require_award(award_id)                               # priority 25
    review = domain.require_env_review(award)                            # priority 28
    if award["award_state"] != "OBLIGATED":                              # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if review["ehp_state"] not in ("SCREENING", "EA_REQUIRED"):          # priority 48
        raise ApiError("ERR_EHP_STATE_INVALID")

    consultation = bool(review["tribal_consultation_required"]) or bool(
        review["shpo_consultation_required"])

    if pathway == "CATEGORICAL_EXCLUSION":
        if review["ehp_state"] != "SCREENING" or consultation:
            raise ApiError(
                "ERR_EHP_STATE_INVALID",
                "A categorical exclusion requires screening with no consultation in scope.")
        target = "CATEGORICAL_EXCLUSION"
    elif pathway == "EA_REQUIRED":
        if review["ehp_state"] != "SCREENING" or not consultation:
            raise ApiError(
                "ERR_EHP_STATE_INVALID",
                "An environmental assessment requires screening with consultation in scope.")
        target = "EA_REQUIRED"
    elif pathway == "MITIGATION_PLAN_ACCEPTED":
        if review["ehp_state"] != "EA_REQUIRED":
            raise ApiError("ERR_EHP_STATE_INVALID")
        if mitigation_summary is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field 'mitigation_summary' is required on the "
                           "MITIGATION_PLAN_ACCEPTED pathway.")
        target = "MITIGATION_REQUIRED"
    else:
        if review["ehp_state"] != "EA_REQUIRED":
            raise ApiError("ERR_EHP_STATE_INVALID")
        target = "BLOCKED"

    assign(review, "pathway", pathway)
    assign(review, "ehp_state", target)
    if pathway == "MITIGATION_PLAN_ACCEPTED":
        assign(review, "mitigation_summary", mitigation_summary)
    touch(review)
    return object_response(serialize(review))


@bp.post("/broadband/awards/<award_id>/environmental-review/clear")
def clear_environmental_review(award_id):
    user_id, _role = authenticate("EnvironmentalReviewer")
    award = domain.require_award(award_id)                               # priority 25
    review = domain.require_env_review(award)                            # priority 28
    if award["award_state"] != "OBLIGATED":                              # priority 45
        raise ApiError("ERR_AWARD_STATE_INVALID")
    if review["ehp_state"] not in ("CATEGORICAL_EXCLUSION", "MITIGATION_REQUIRED",
                                   "BLOCKED"):                          # priority 48
        raise ApiError("ERR_EHP_STATE_INVALID")
    if review["ehp_state"] == "BLOCKED":                                 # priority 56
        raise ApiError("ERR_EHP_ADVERSE_EFFECT_BLOCKING")
    if (review["ehp_state"] == "MITIGATION_REQUIRED"
            and review.get("mitigation_summary") is None):
        raise ApiError("ERR_EHP_STATE_INVALID",
                       "Clearance from MITIGATION_REQUIRED requires a mitigation summary.")

    assign(review, "ehp_state", "CLEARED")
    assign(review, "cleared_by_user_id", user_id)
    assign(review, "cleared_at", now_ts())
    touch(review)
    return object_response(serialize(review))
