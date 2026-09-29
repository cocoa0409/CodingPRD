"""Permit application filing, screening, review routing and revision cycles."""
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

bp = Blueprint("applications", __name__)

VOID_FROM = ("DRAFT", "SUBMITTED_FOR_QA", "RETURNED", "ACCEPTED", "INVALIDATED")
WITHDRAWABLE = (
    "DRAFT",
    "SUBMITTED",
    "STANDARD_REVIEW",
    "ENHANCED_REVIEW",
    "PENDING_DECISION",
    "RETURNED_FOR_REVISION",
)


def _own_or_403(application, user_id):
    if application["facility_id"] != user_id:
        raise ApiError("ERR_NOT_APPLICATION_OWNER")


# ------------------------------------------------------------------------ create
@bp.post("/ej/permit-applications")
def create_application():
    user_id, _ = authenticate((C.ROLE_APPLICANT_REP,))
    body = body_json()
    facility_id = f_str(body, "facility_id")
    permit_type = f_enum(body, "permit_type", C.PERMIT_TYPES)
    proposed_emissions_tpy = f_num(body, "proposed_emissions_tpy",
                                   exclusive_min=C.D("0"))
    hours = f_int(body, "proposed_operating_hours_per_year", minimum=1, maximum=8760)
    prior_application_id = f_str(body, "prior_application_id", required=False)

    facility = repo.get_facility(facility_id)
    if prior_application_id is not None:
        repo.get_application(prior_application_id)

    if facility["id"] != user_id:
        raise ApiError("ERR_NOT_APPLICATION_OWNER")

    row = new_row()
    row.update(
        {
            "facility_id": facility["id"],
            "prior_application_id": prior_application_id,
            "permit_type": permit_type,
            "proposed_emissions_tpy": proposed_emissions_tpy,
            "proposed_operating_hours_per_year": hours,
            "status": "DRAFT",
            "review_track": "UNDETERMINED",
            "revision_round": 0,
            "screening_stale_flag": False,
            "pre_mitigation_index": C.D("0.00"),
            "total_mitigation_credit_tpy": C.D("0.00"),
            "residual_impact_index": C.D("0.00"),
            "approved_net_emissions_tpy": C.D("0.00"),
        }
    )
    db.permit_applications[row["id"]] = row
    return object_response(serialize.permit_application(row), 201)


# -------------------------------------------------------------------------- reads
@bp.get("/ej/permit-applications/<application_id>")
def read_application(application_id):
    authenticate(C.READ_NO_PUBLIC)
    application = repo.get_application(application_id)
    return object_response(serialize.permit_application(application))


@bp.get("/ej/facilities/<facility_id>/permit-applications")
def list_facility_applications(facility_id):
    authenticate(C.READ_NO_PUBLIC)
    limit, offset = q_pagination()
    status = q_enum("status", C.APPLICATION_STATUSES)
    review_track = q_enum("review_track", C.REVIEW_TRACKS)
    facility = repo.get_facility(facility_id)
    rows = repo.applications_of_facility(facility["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if review_track is not None:
        rows = [r for r in rows if r["review_track"] == review_track]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.permit_application, page),
                         limit, offset, total)


@bp.get("/ej/permit-applications/<application_id>/revisions")
def list_application_revisions(application_id):
    authenticate(C.READ_NO_PUBLIC)
    limit, offset = q_pagination()
    application = repo.get_application(application_id)
    from db import ordered

    rows = ordered([r for r in db.permit_applications.values()
                    if r["prior_application_id"] == application["id"]])
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.permit_application, page),
                         limit, offset, total)


@bp.get("/ej/permit-applications/<application_id>/applicability-determinations")
def list_determinations(application_id):
    authenticate(C.READ_NO_INSPECTOR_NO_PUBLIC)
    limit, offset = q_pagination()
    application = repo.get_application(application_id)
    rows = repo.determinations_of(application["id"])
    # The single documented ordering exception: revision_round DESC, created_at DESC.
    rows.sort(key=lambda r: (r["revision_round"], r["created_at"], r["_seq"]),
              reverse=True)
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.applicability_determination, page),
                         limit, offset, total)


# ------------------------------------------------------------------- transitions
@bp.post("/ej/permit-applications/<application_id>/submit")
def submit_application(application_id):
    user_id, _ = authenticate((C.ROLE_APPLICANT_REP,))
    body_json()
    application = repo.get_application(application_id)
    _own_or_403(application, user_id)
    if application["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_APPLICATION_STATE")
    application["status"] = "SUBMITTED"
    touch(application)
    return object_response(serialize.permit_application(application))


@bp.post("/ej/permit-applications/<application_id>/screen")
def screen_application(application_id):
    user_id, _ = authenticate((C.ROLE_EJ_ANALYST,))
    body_json()
    application = repo.get_application(application_id)
    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    facility = repo.facility_of_application(application)
    area = repo.area_of_facility(facility)
    codes = calc.applicability_trigger_codes(facility, area, application)
    determination = cascade.write_determination(application, area, codes, user_id)

    if codes:
        application["review_track"] = "ENHANCED"
        application["status"] = "ENHANCED_REVIEW"
        plan = repo.live_plan_of(application["id"])
        if plan is None:
            cascade.create_plan(application, area)
        else:
            cascade.recompute_plan_days(plan, area)
    else:
        application["review_track"] = "STANDARD"
        application["status"] = "STANDARD_REVIEW"

    touch(application)
    determination["application_version_after"] = application["version"]
    return object_response(serialize.applicability_determination(determination), 201)


@bp.post("/ej/permit-applications/<application_id>/advance-to-decision")
def advance_to_decision(application_id):
    authenticate((C.ROLE_EJ_ANALYST,))
    body_json()
    application = repo.get_application(application_id)
    if application["status"] not in ("STANDARD_REVIEW", "ENHANCED_REVIEW"):
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    if application["review_track"] == "ENHANCED":
        governing = cascade.governing_assessment(application)
        if governing is None or governing["status"] != "ACCEPTED":
            raise ApiError("ERR_ASSESSMENT_NOT_ACCEPTED")
        plan = repo.live_plan_of(application["id"])
        if plan is None or plan["status"] != "CLOSED":
            raise ApiError("ERR_PARTICIPATION_NOT_CLOSED")
        cascade.recompute_indices(application)

    application["status"] = "PENDING_DECISION"
    touch(application)
    return object_response(serialize.permit_application(application))


@bp.post("/ej/permit-applications/<application_id>/return-for-revision")
def return_for_revision(application_id):
    authenticate((C.ROLE_EJ_ANALYST,))
    body = body_json()
    f_str(body, "reason", min_len=1)
    application = repo.get_application(application_id)
    if application["status"] not in ("ENHANCED_REVIEW", "PENDING_DECISION"):
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    invalidated = cascade.transition_assessments(
        application, ("SUBMITTED_FOR_QA", "ACCEPTED"), "INVALIDATED"
    )
    application["status"] = "RETURNED_FOR_REVISION"
    cascade.recompute_indices(application)
    touch(application)
    cascade.stamp_assessments(invalidated, application)
    return object_response(serialize.permit_application(application))


@bp.post("/ej/permit-applications/<application_id>/resubmit")
def resubmit_application(application_id):
    user_id, _ = authenticate((C.ROLE_APPLICANT_REP,))
    body = body_json()
    proposed_emissions_tpy = f_num(body, "proposed_emissions_tpy", required=False,
                                   exclusive_min=C.D("0"))
    hours = f_int(body, "proposed_operating_hours_per_year", required=False,
                  minimum=1, maximum=8760)

    application = repo.get_application(application_id)
    _own_or_403(application, user_id)
    if application["status"] != "RETURNED_FOR_REVISION":
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    if proposed_emissions_tpy is not None:
        application["proposed_emissions_tpy"] = proposed_emissions_tpy
    if hours is not None:
        application["proposed_operating_hours_per_year"] = hours

    voided = cascade.transition_assessments(application, VOID_FROM, "VOIDED")
    application["status"] = "SUBMITTED"
    application["revision_round"] = application["revision_round"] + 1
    application["screening_stale_flag"] = False

    plan = repo.live_plan_of(application["id"])
    if plan is not None and plan["status"] == "CLOSED":
        cascade.reopen_plan(plan, repo.area_of_application(application))

    cascade.recompute_indices(application)
    touch(application)
    cascade.stamp_assessments(voided, application)
    return object_response(serialize.permit_application(application))


@bp.post("/ej/permit-applications/<application_id>/withdraw")
def withdraw_application(application_id):
    user_id, _ = authenticate((C.ROLE_APPLICANT_REP,))
    body = body_json()
    f_str(body, "reason", required=False)

    application = repo.get_application(application_id)
    _own_or_403(application, user_id)
    if application["status"] not in WITHDRAWABLE:
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    area = repo.area_of_application(application)
    cascade.cancel_plan_cascade(application, area)
    voided = cascade.transition_assessments(application, VOID_FROM, "VOIDED")

    voided_conditions = []
    for condition in repo.conditions_of(application["id"]):
        if condition["status"] == "ACTIVE":
            condition["status"] = "VOIDED"
            touch(condition)
            voided_conditions.append(condition)

    application["status"] = "WITHDRAWN"
    cascade.recompute_credit(application)
    cascade.recompute_indices(application)
    touch(application)
    cascade.stamp_assessments(voided, application)
    cascade.stamp_assessments(voided_conditions, application)
    return object_response(serialize.permit_application(application))
