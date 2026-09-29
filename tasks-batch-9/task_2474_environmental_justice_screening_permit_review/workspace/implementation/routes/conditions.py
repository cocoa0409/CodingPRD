"""Permit conditions, issuance / denial and rescission."""
from flask import Blueprint

import constants as C
import serialize
from db import db, new_row, touch
from errors import ApiError
from middleware import authenticate
from response import list_response, object_response, paginate
from services import calc, cascade, repo
from validators import (body_json, f_bool, f_enum, f_int, f_num, f_str, q_enum,
                        q_pagination)

bp = Blueprint("conditions", __name__)

CONDITION_APP_STATES = ("STANDARD_REVIEW", "ENHANCED_REVIEW", "PENDING_DECISION")


# ---------------------------------------------------------------------- conditions
@bp.post("/ej/permit-conditions")
def create_condition():
    authenticate((C.ROLE_EJ_ANALYST,))
    body = body_json()
    permit_application_id = f_str(body, "permit_application_id")
    condition_type = f_enum(body, "condition_type", C.CONDITION_TYPES)
    reduction_tpy = f_num(body, "reduction_tpy", required=False,
                          default=C.D("0.00"), minimum=C.D("0"))
    enforceable = f_bool(body, "enforceable", required=False, default=False)
    monitoring_frequency = f_enum(body, "monitoring_frequency",
                                  C.MONITORING_FREQUENCIES, required=False)
    benefit_value_usd = f_num(body, "benefit_value_usd", required=False,
                              minimum=C.D("0"))
    expected_version = f_int(body, "expected_application_version")

    application = repo.get_application(permit_application_id)

    if expected_version != application["version"]:
        raise ApiError("ERR_STALE_APPLICATION_VERSION")
    if condition_type == "MONITORING" and monitoring_frequency is None:
        raise ApiError("ERR_CONDITION_INPUTS_REQUIRED")
    if condition_type == "COMMUNITY_BENEFIT" and benefit_value_usd is None:
        raise ApiError("ERR_CONDITION_INPUTS_REQUIRED")
    if application["status"] not in CONDITION_APP_STATES:
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    row = new_row()
    row.update(
        {
            "permit_application_id": application["id"],
            "condition_type": condition_type,
            "reduction_tpy": reduction_tpy,
            "enforceable": enforceable,
            "monitoring_frequency": monitoring_frequency,
            "benefit_value_usd": benefit_value_usd,
            "credit_tpy": C.D("0.00"),
            "status": "ACTIVE",
            "application_version_after": application["version"],
        }
    )
    row["credit_tpy"] = calc.condition_credit(row)
    db.permit_conditions[row["id"]] = row

    cascade.recompute_credit(application)
    touch(application)
    row["application_version_after"] = application["version"]
    return object_response(serialize.permit_condition(row), 201)


@bp.get("/ej/permit-applications/<application_id>/conditions")
def list_application_conditions(application_id):
    authenticate(C.READ_NO_INSPECTOR_NO_PUBLIC)
    limit, offset = q_pagination()
    status = q_enum("status", C.CONDITION_STATUSES)
    application = repo.get_application(application_id)
    rows = repo.conditions_of(application["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.permit_condition, page),
                         limit, offset, total)


@bp.delete("/ej/permit-conditions/<condition_id>")
def void_condition(condition_id):
    authenticate((C.ROLE_EJ_ANALYST,))
    condition = repo.get_condition(condition_id)
    if condition["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_CONDITION_STATE")
    application = db.permit_applications[condition["permit_application_id"]]
    if application["status"] not in CONDITION_APP_STATES:
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    condition["status"] = "VOIDED"
    touch(condition)
    cascade.recompute_credit(application)
    touch(application)
    condition["application_version_after"] = application["version"]
    return "", 204


# ----------------------------------------------------------------------- decisions
@bp.post("/ej/permit-decisions")
def create_decision():
    user_id, _ = authenticate((C.ROLE_PERMIT_MANAGER,))
    body = body_json()
    permit_application_id = f_str(body, "permit_application_id")
    disposition = f_enum(body, "disposition", C.DISPOSITIONS)
    denial_basis = f_enum(body, "denial_basis", C.DENIAL_BASES, required=False)
    base = f_num(body, "community_benefit_base_usd", required=False,
                 minimum=C.D("0"))

    application = repo.get_application(permit_application_id)

    if application["status"] != "PENDING_DECISION":
        raise ApiError("ERR_INVALID_APPLICATION_STATE")

    governing = cascade.governing_assessment(application)
    if governing is not None and user_id in (governing["author_user_id"],
                                             governing["qa_user_id"]):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    enhanced = application["review_track"] == "ENHANCED"
    if enhanced and (governing is None or governing["status"] != "ACCEPTED"):
        raise ApiError("ERR_ASSESSMENT_NOT_ACCEPTED")

    facility = repo.facility_of_application(application)
    area = repo.area_of_facility(facility)
    plan = repo.live_plan_of(application["id"])
    designated = area["designation"] != "UNDESIGNATED"

    approved_net = calc.approved_net_emissions(
        application["proposed_emissions_tpy"],
        application["total_mitigation_credit_tpy"],
    )

    if disposition == "ISSUE":
        if enhanced and (plan is None or plan["adequacy_status"] != "COMPLIANT"):
            raise ApiError("ERR_PARTICIPATION_INADEQUATE")
        if application["residual_impact_index"] >= C.DENIAL_THRESHOLD:
            raise ApiError("ERR_DISPROPORTIONATE_IMPACT_UNMITIGATED")
        if designated and base is None:
            raise ApiError("ERR_BENEFIT_BASE_REQUIRED")

        effective_base = base if base is not None else C.D("0.00")
        surcharge, total = calc.community_benefit(effective_base, area["designation"])
        if designated and total < calc.minimum_benefit_required(approved_net):
            raise ApiError("ERR_BENEFIT_COMMITMENT_INSUFFICIENT")
        if area["permitted_load_tpy"] + approved_net > calc.area_load_cap(
            area["baseline_load_tpy"]
        ):
            raise ApiError("ERR_AREA_LOAD_CAP_EXCEEDED")

        application["status"] = "ISSUED"
        application["approved_net_emissions_tpy"] = approved_net
        touch(application)

        facility["existing_load_tpy"] = facility["existing_load_tpy"] + approved_net
        touch(facility)
        area["permitted_load_tpy"] = area["permitted_load_tpy"] + approved_net
        touch(area)

        row = new_row()
        row.update(
            {
                "permit_application_id": application["id"],
                "disposition": disposition,
                "denial_basis": None,
                "community_benefit_base_usd": base,
                "community_benefit_surcharge_usd": surcharge,
                "community_benefit_total_usd": total,
                "residual_index_at_decision": application["residual_impact_index"],
                "approved_net_emissions_tpy": approved_net,
                "decided_by_user_id": user_id,
                "status": "ISSUED",
            }
        )
        db.permit_decisions[row["id"]] = row
        return object_response(serialize.permit_decision(row), 201)

    # ------------------------------------------------------------------- DENY
    supported = False
    if denial_basis == "UNMITIGABLE_DISPROPORTIONATE_IMPACT":
        supported = application["residual_impact_index"] >= C.DENIAL_THRESHOLD
    elif denial_basis == "INADEQUATE_PARTICIPATION":
        supported = plan is not None and plan["adequacy_status"] == "DEFICIENT"
    elif denial_basis == "INCOMPLETE_ASSESSMENT":
        supported = governing is not None and governing["data_confidence"] == "LOW"
    if not supported:
        raise ApiError("ERR_DENIAL_BASIS_UNSUPPORTED")

    application["status"] = "DENIED"
    touch(application)

    row = new_row()
    row.update(
        {
            "permit_application_id": application["id"],
            "disposition": disposition,
            "denial_basis": denial_basis,
            "community_benefit_base_usd": base,
            "community_benefit_surcharge_usd": C.D("0.00"),
            "community_benefit_total_usd": C.D("0.00"),
            "residual_index_at_decision": application["residual_impact_index"],
            "approved_net_emissions_tpy": C.D("0.00"),
            "decided_by_user_id": user_id,
            "status": "DENIED",
        }
    )
    db.permit_decisions[row["id"]] = row
    return object_response(serialize.permit_decision(row), 201)


@bp.get("/ej/permit-applications/<application_id>/decisions")
def list_application_decisions(application_id):
    authenticate(C.READ_NO_INSPECTOR)
    limit, offset = q_pagination()
    application = repo.get_application(application_id)
    rows = repo.decisions_of(application["id"])
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.permit_decision, page),
                         limit, offset, total)


@bp.post("/ej/permit-decisions/<decision_id>/rescind")
def rescind_decision(decision_id):
    authenticate((C.ROLE_PERMIT_MANAGER,))
    body = body_json()
    f_str(body, "reason", min_len=1)

    decision = repo.get_decision(decision_id)
    if decision["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_DECISION_STATE")

    application = db.permit_applications[decision["permit_application_id"]]
    facility = repo.facility_of_application(application)
    area = repo.area_of_facility(facility)
    amount = application["approved_net_emissions_tpy"]

    decision["status"] = "RESCINDED"
    touch(decision)

    facility["existing_load_tpy"] = facility["existing_load_tpy"] - amount
    touch(facility)
    area["permitted_load_tpy"] = area["permitted_load_tpy"] - amount
    touch(area)

    application["approved_net_emissions_tpy"] = C.D("0.00")
    enhanced = application["review_track"] == "ENHANCED"
    application["status"] = "ENHANCED_REVIEW" if enhanced else "STANDARD_REVIEW"

    invalidated = []
    if enhanced:
        for row in repo.assessments_of(application["id"]):
            if row["status"] == "ACCEPTED":
                row["status"] = "INVALIDATED"
                touch(row)
                invalidated.append(row)
        plan = repo.live_plan_of(application["id"])
        if plan is not None and plan["status"] == "CLOSED":
            cascade.reopen_plan(plan, area)

    cascade.recompute_indices(application)
    touch(application)
    cascade.stamp_assessments(invalidated, application)
    return object_response(serialize.permit_decision(decision))
