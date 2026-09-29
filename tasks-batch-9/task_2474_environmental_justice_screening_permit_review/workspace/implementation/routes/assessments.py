"""Cumulative impact assessments and the independent QA loop."""
from flask import Blueprint

import constants as C
import serialize
from db import db, new_row, touch
from errors import ApiError
from middleware import authenticate
from response import list_response, object_response, paginate
from services import calc, cascade, repo
from validators import (body_json, f_enum, f_int, f_num, f_str, q_enum,
                        q_pagination)

bp = Blueprint("assessments", __name__)


def _require_refined_inputs(method, dispersion_factor, receptor_distance_m):
    if method == "REFINED" and (dispersion_factor is None or receptor_distance_m is None):
        raise ApiError("ERR_REFINED_INPUTS_REQUIRED")


def _compute(assessment, application, area):
    """Write the pinned-order index and both derived findings."""
    assessment["baseline_burden_score"] = area["ej_screen_score_statewide"]
    increment, exposure, index = calc.cumulative_impact_index(
        area["ej_screen_score_statewide"],
        application["proposed_emissions_tpy"],
        area["baseline_load_tpy"],
        assessment["method"],
        assessment["dispersion_factor"],
        assessment["receptor_distance_m"],
    )
    assessment["proposed_increment_pct"] = increment
    assessment["exposure_factor"] = exposure
    assessment["cumulative_impact_index"] = index
    assessment["disproportionate_flag"] = calc.disproportionate(index)
    assessment["data_confidence"] = calc.data_confidence_for(
        area["active_indicator_count"], area["data_status"]
    )


@bp.post("/ej/cumulative-impact-assessments")
def create_assessment():
    user_id, _ = authenticate((C.ROLE_EJ_ANALYST,))
    body = body_json()
    permit_application_id = f_str(body, "permit_application_id")
    method = f_enum(body, "method", C.ASSESSMENT_METHODS)
    dispersion_factor = f_num(body, "dispersion_factor", required=False,
                              minimum=C.D("0.10"), maximum=C.D("1.00"))
    receptor_distance_m = f_int(body, "receptor_distance_m", required=False, minimum=0)
    expected_version = f_int(body, "expected_application_version")

    application = repo.get_application(permit_application_id)

    if expected_version != application["version"]:
        raise ApiError("ERR_STALE_APPLICATION_VERSION")
    _require_refined_inputs(method, dispersion_factor, receptor_distance_m)

    if method == "SCREENING_LEVEL":
        dispersion_factor = None
        receptor_distance_m = None

    area = repo.area_of_application(application)

    superseded = []
    for existing in repo.assessments_of(application["id"]):
        if existing["status"] in ("DRAFT", "RETURNED"):
            existing["status"] = "SUPERSEDED"
            touch(existing)
            superseded.append(existing)

    row = new_row()
    row.update(
        {
            "permit_application_id": application["id"],
            "method": method,
            "dispersion_factor": dispersion_factor,
            "receptor_distance_m": receptor_distance_m,
            "author_user_id": user_id,
            "qa_user_id": None,
            "baseline_burden_score": C.D("0.00"),
            "proposed_increment_pct": C.D("0.00"),
            "exposure_factor": C.D("0.0000"),
            "cumulative_impact_index": C.D("0.00"),
            "disproportionate_flag": False,
            "data_confidence": "HIGH",
            "status": "DRAFT",
            "application_version_after": application["version"],
        }
    )
    _compute(row, application, area)
    db.assessments[row["id"]] = row

    cascade.recompute_indices(application)
    touch(application)
    row["application_version_after"] = application["version"]
    cascade.stamp_assessments(superseded, application)
    return object_response(serialize.assessment(row), 201)


@bp.get("/ej/permit-applications/<application_id>/assessments")
def list_application_assessments(application_id):
    authenticate(C.READ_NO_INSPECTOR_NO_PUBLIC)
    limit, offset = q_pagination()
    status = q_enum("status", C.ASSESSMENT_STATUSES)
    application = repo.get_application(application_id)
    rows = repo.assessments_of(application["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.assessment, page),
                         limit, offset, total)


@bp.post("/ej/cumulative-impact-assessments/<assessment_id>/submit-qa")
def submit_for_qa(assessment_id):
    authenticate((C.ROLE_EJ_ANALYST,))
    body_json()
    assessment = repo.get_assessment(assessment_id)
    if assessment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE")
    application = db.permit_applications[assessment["permit_application_id"]]
    if application["status"] not in ("ENHANCED_REVIEW", "PENDING_DECISION"):
        raise ApiError("ERR_INVALID_APPLICATION_STATE")
    assessment["status"] = "SUBMITTED_FOR_QA"
    touch(assessment)
    return object_response(serialize.assessment(assessment))


@bp.post("/ej/cumulative-impact-assessments/<assessment_id>/qa-decision")
def qa_decision(assessment_id):
    user_id, _ = authenticate((C.ROLE_QA_REVIEWER,))
    body = body_json()
    outcome = f_enum(body, "outcome", C.QA_OUTCOMES)
    f_str(body, "note", required=False)

    assessment = repo.get_assessment(assessment_id)
    if assessment["status"] != "SUBMITTED_FOR_QA":
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE")
    if user_id == assessment["author_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    application = db.permit_applications[assessment["permit_application_id"]]
    assessment["qa_user_id"] = user_id

    if outcome == "RETURN":
        assessment["status"] = "RETURNED"
        touch(assessment)
        return object_response(serialize.assessment(assessment))

    superseded = []
    for other in repo.assessments_of(application["id"]):
        if other["id"] != assessment["id"] and other["status"] == "ACCEPTED":
            other["status"] = "SUPERSEDED"
            touch(other)
            superseded.append(other)

    assessment["status"] = "ACCEPTED"
    touch(assessment)

    application["pre_mitigation_index"] = assessment["cumulative_impact_index"]
    cascade.recompute_residual(application)
    touch(application)

    plan = repo.live_plan_of(application["id"])
    if plan is not None and plan["status"] in ("PLANNED", "OPEN", "EXTENDED"):
        cascade.recompute_plan_days(plan, repo.area_of_application(application))

    assessment["application_version_after"] = application["version"]
    cascade.stamp_assessments(superseded, application)
    return object_response(serialize.assessment(assessment))


@bp.post("/ej/cumulative-impact-assessments/<assessment_id>/revise")
def revise_assessment(assessment_id):
    user_id, _ = authenticate((C.ROLE_EJ_ANALYST,))
    body = body_json()
    method = f_enum(body, "method", C.ASSESSMENT_METHODS, required=False)
    dispersion_factor = f_num(body, "dispersion_factor", required=False,
                              minimum=C.D("0.10"), maximum=C.D("1.00"))
    receptor_distance_m = f_int(body, "receptor_distance_m", required=False, minimum=0)

    assessment = repo.get_assessment(assessment_id)
    if assessment["status"] != "RETURNED":
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE")

    effective_method = method if method is not None else assessment["method"]
    effective_dispersion = (
        dispersion_factor if dispersion_factor is not None
        else assessment["dispersion_factor"]
    )
    effective_receptor = (
        receptor_distance_m if receptor_distance_m is not None
        else assessment["receptor_distance_m"]
    )
    _require_refined_inputs(effective_method, effective_dispersion, effective_receptor)

    if effective_method == "SCREENING_LEVEL":
        effective_dispersion = None
        effective_receptor = None

    assessment["method"] = effective_method
    assessment["dispersion_factor"] = effective_dispersion
    assessment["receptor_distance_m"] = effective_receptor
    assessment["author_user_id"] = user_id
    assessment["status"] = "DRAFT"

    application = db.permit_applications[assessment["permit_application_id"]]
    _compute(assessment, application, repo.area_of_application(application))
    touch(assessment)
    return object_response(serialize.assessment(assessment))
