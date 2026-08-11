"""OutcomeAssessment endpoints."""

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch
from middleware import require_roles, ALL_ROLES
from response import success_object
from services.calculations import outcome_provisional_composite, outcome_final_composite

bp = Blueprint("outcomes", __name__)


@bp.post("/api/outcome-assessments")
def create_outcome_assessment():
    require_roles(["VisionSpecialist"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {
        "client_id", "kind", "task_score", "satisfaction_score", "acuity_delta",
    })
    client_id = v.req_string(body, "client_id")
    kind = v.req_enum(body, "kind", {"BASELINE", "FOLLOW_UP"})
    task_score = v.req_int(body, "task_score", min_v=0, max_v=100)
    satisfaction_score = v.req_int(body, "satisfaction_score", min_v=0, max_v=100)
    acuity_delta = v.opt_int(body, "acuity_delta", default=None, min_v=0, max_v=100)

    if client_id not in store.clients:
        raise errors.not_found("Client not found")

    assessment = new_entity()
    assessment.update({
        "client_id": client_id,
        "kind": kind,
        "task_score": task_score,
        "satisfaction_score": satisfaction_score,
        "acuity_delta": acuity_delta,
        "provisional_composite": outcome_provisional_composite(task_score, satisfaction_score),
        "final_composite": None,
        "status": "DRAFT",
    })
    store.outcome_assessments[assessment["id"]] = assessment
    return success_object(assessment, status=201)


@bp.get("/api/outcome-assessments/<aid>")
def get_outcome_assessment(aid):
    require_roles(ALL_ROLES)
    assessment = store.outcome_assessments.get(aid)
    if assessment is None:
        raise errors.not_found("OutcomeAssessment not found")
    return success_object(assessment)


@bp.post("/api/outcome-assessments/<aid>/finalize")
def finalize_outcome_assessment(aid):
    require_roles(["VisionSpecialist"])
    body = request.get_json(silent=True)
    if body is not None:
        if not isinstance(body, dict):
            raise errors.validation("Request body must be a JSON object")
        v.reject_unknown_fields(body, {"acuity_delta"})
        acuity_delta = v.opt_int(body, "acuity_delta", default=None, min_v=0, max_v=100)
    else:
        acuity_delta = None

    assessment = store.outcome_assessments.get(aid)
    if assessment is None:
        raise errors.not_found("OutcomeAssessment not found")
    if assessment["status"] != "DRAFT":
        raise errors.invalid_state("Assessment is not DRAFT")

    if acuity_delta is not None:
        assessment["acuity_delta"] = acuity_delta
    if assessment["acuity_delta"] is None:
        raise errors.assessment_incomplete("acuity_delta is required to finalize")

    assessment["final_composite"] = outcome_final_composite(
        assessment["acuity_delta"], assessment["task_score"], assessment["satisfaction_score"],
    )
    assessment["status"] = "SCORED"
    touch(assessment)
    return success_object(assessment)
