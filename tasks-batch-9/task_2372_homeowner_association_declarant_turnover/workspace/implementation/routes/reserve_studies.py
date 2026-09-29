"""Reserve studies: draft creation, adequacy evaluation and adoption."""
from flask import Blueprint

import auth
import calc
import cascades
import constants
import response
import validation as v
from db import db, new_record, serialize, touch
from errors import ApiError
from routes import common

bp = Blueprint("reserve_studies", __name__)


@bp.post("/hoa/reserve-studies")
def create_study():
    auth.require_roles(constants.ROLE_TRANSITION_COMMITTEE)
    body = v.body()

    association = common.body_association_or_404(v.get_fk(body, "association_id"))
    if association is None:
        raise ApiError("ERR_INVALID_REQUEST", "association_id is required.")

    funding_method = v.get_enum(body, "funding_method", constants.FUNDING_METHODS)
    planned = v.get_int(body, "planned_annual_contribution_cents", minimum=0)
    projected = v.get_int(body, "projected_annual_expenditure_cents", minimum=0)

    cascades.require_not_settled_locked(association["id"])

    # a newer draft supersedes any live draft of the same association
    for existing in calc.studies_of(association["id"]):
        if existing["status"] == "DRAFT":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    study = new_record({
        "association_id": association["id"],
        "funding_method": funding_method,
        "planned_annual_contribution_cents": planned,
        "projected_annual_expenditure_cents": projected,
        "evaluated_method": None,
        "component_count": 0,
        "fully_funded_balance_cents": 0,
        "percent_funded": 0.00,
        "min_projected_balance_cents": 0,
        "adequacy_verdict": "UNDETERMINED",
        "recommended_annual_contribution_cents": 0,
        "status": "DRAFT",
    })
    db.reserve_studies[study["id"]] = study
    return response.object_response(serialize(study), 201)


@bp.post("/hoa/reserve-studies/<study_id>/actions")
def study_action(study_id):
    auth.require_roles(constants.ROLE_TRANSITION_COMMITTEE)
    study = common.reserve_study_or_404(study_id, scoped=True)
    body = v.body()
    action = v.get_enum(body, "action", constants.RESERVE_STUDY_ACTIONS)
    method = None
    if action == "RECOMPUTE":
        method = v.get_enum(body, "method", constants.FUNDING_METHODS)

    cascades.require_not_settled_locked(study["association_id"])

    if study["status"] != "DRAFT":
        raise ApiError("ERR_NOT_IN_DRAFT")

    association = db.associations[study["association_id"]]

    if action == "RECOMPUTE":
        calc.apply_reserve_adequacy(study, association, method)
        touch(study)
        return response.object_response(serialize(study))

    # ---- ADOPT ----
    if study["evaluated_method"] is None or study["adequacy_verdict"] == "UNDETERMINED":
        raise ApiError("ERR_ADEQUACY_NOT_EVALUATED")

    for existing in calc.studies_of(association["id"]):
        if existing["id"] != study["id"] and existing["status"] == "ADOPTED":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    study["status"] = "ADOPTED"
    touch(study)
    return response.object_response(serialize(study))
