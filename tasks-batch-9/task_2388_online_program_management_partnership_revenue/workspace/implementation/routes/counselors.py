"""EnrollmentCounselor onboarding, compensation filing and compliance review."""

from flask import Blueprint, request

import constants as C
import db
import serializers
from db import store, touch
from errors import ApiError
from middleware import authenticate, body, check_scope, scope_filter
from response import object_response
from routes.common import get_counselor, get_partnership, listing
from services.money import D
from validation import Field, enum_filter, pagination_args, validate_body

bp = Blueprint("counselors", __name__)

READ_ROLES = ("PlatformAdmin", "UniversityProvost", "UniversityBursar",
              "ComplianceAuditor", "PartnerAccountLead")

CREATE_SPEC = {
    "partnership_id": Field("string", required=True),
    "full_name": Field("string", required=True),
    "employer": Field("enum", required=True, enum=C.PARTIES),
    "monthly_base_salary_cents": Field("integer", required=True),
}

PLAN_SPEC = {
    "comp_plan_type": Field("enum", required=True, enum=C.COMP_PLAN_TYPES_REQUEST),
    "annual_base_cents": Field("integer", required=True),
    "variable_component_cents": Field("integer"),
    "variable_basis": Field("enum", enum=C.VARIABLE_BASES_REQUEST),
}

REVIEW_SPEC = {
    "decision": Field("enum", required=True, enum=("APPROVE", "SUSPEND", "REJECT_PLAN")),
    "reviewer_note": Field("string"),
}

PROHIBITED_PLAN_TYPES = ("PER_ENROLLMENT_COMMISSION", "PER_APPLICATION_BOUNTY")
PROHIBITED_BASES = ("ENROLLMENT_COUNT", "APPLICATION_COUNT")


@bp.post("/enrollment-counselors")
def create():
    uid, role = authenticate(("PartnerAccountLead",))
    values = validate_body(body(), CREATE_SPEC)
    partnership = get_partnership(values["partnership_id"])
    check_scope(role, uid, partnership["id"])

    counselor = db.base_entity()
    counselor.update({
        "partnership_id": partnership["id"],
        "full_name": values["full_name"],
        "employer": values["employer"],
        "monthly_base_salary_cents": values["monthly_base_salary_cents"],
        "comp_plan_type": "NONE_ON_FILE",
        "annual_base_cents": 0,
        "variable_component_cents": 0,
        "variable_basis": "NONE",
        "performance_status": "NOT_RATED",
        "incentive_eligibility": "PENDING_COMPLIANCE_REVIEW",
        "conversion_rate": 0.0,
        "open_pipeline_count": 0,
        "rated_lead_count": 0,
        "enrolled_lead_count": 0,
        "sla_breach_count": 0,
        "clawback_pending_cents": 0,
        "last_review_user_id": None,
    })
    store.counselors[counselor["id"]] = counselor
    return object_response(serializers.counselor(counselor), 201)


@bp.get("/enrollment-counselors/<counselor_id>")
def read(counselor_id):
    uid, role = authenticate(READ_ROLES)
    counselor = get_counselor(counselor_id)
    check_scope(role, uid, counselor["partnership_id"])
    return object_response(serializers.counselor(counselor))


@bp.get("/enrollment-counselors")
def index():
    uid, role = authenticate(READ_ROLES)
    limit, offset = pagination_args(request.args)
    performance = enum_filter(request.args, "performance_status", C.PERFORMANCE_STATUSES)
    incentive = enum_filter(request.args, "incentive_eligibility",
                            C.INCENTIVE_ELIGIBILITIES)
    partnership_id = scope_filter(role, uid, request.args.get("partnership_id"))

    items = db.sort_created(list(store.counselors.values()))
    if partnership_id is not None:
        items = [c for c in items if c["partnership_id"] == partnership_id]
    if performance is not None:
        items = [c for c in items if c["performance_status"] == performance]
    if incentive is not None:
        items = [c for c in items if c["incentive_eligibility"] == incentive]
    return listing(items, serializers.counselor, limit, offset)


@bp.post("/enrollment-counselors/<counselor_id>/compensation-plan")
def file_plan(counselor_id):
    uid, role = authenticate(("PartnerAccountLead",))
    values = validate_body(body(), PLAN_SPEC)
    counselor = get_counselor(counselor_id)
    check_scope(role, uid, counselor["partnership_id"])

    partnership = get_partnership(counselor["partnership_id"])
    if partnership["status"] != "EXECUTED":
        raise ApiError("ERR_PARTNERSHIP_INVALID_STATE")

    plan_type = values["comp_plan_type"]
    basis = values.get("variable_basis", "NONE")
    variable = values.get("variable_component_cents", 0)

    if plan_type in PROHIBITED_PLAN_TYPES or basis in PROHIBITED_BASES:
        raise ApiError("ERR_INCENTIVE_COMP_PROHIBITED")
    if (plan_type == "SALARY_PLUS_QUALITATIVE" and basis == "QUALITATIVE_MULTI_FACTOR"
            and not partnership["bundled_services_exception_claimed"]):
        raise ApiError("ERR_INCENTIVE_COMP_PROHIBITED")

    if D(variable) * D(100) > D(values["annual_base_cents"]) * D(20):
        raise ApiError("ERR_COMP_EXCEEDS_APPROVED_ENVELOPE")

    counselor["comp_plan_type"] = plan_type
    counselor["annual_base_cents"] = values["annual_base_cents"]
    counselor["variable_component_cents"] = variable
    counselor["variable_basis"] = basis
    counselor["incentive_eligibility"] = "PENDING_COMPLIANCE_REVIEW"
    touch(counselor)
    return object_response(serializers.counselor(counselor))


REVIEW_TRANSITIONS = {
    "APPROVE": (("PENDING_COMPLIANCE_REVIEW",), "ELIGIBLE"),
    "REJECT_PLAN": (("PENDING_COMPLIANCE_REVIEW",), "PROHIBITED_PLAN_ON_FILE"),
    "SUSPEND": (("PENDING_COMPLIANCE_REVIEW", "ELIGIBLE"), "SUSPENDED"),
}


@bp.post("/enrollment-counselors/<counselor_id>/compliance-review")
def compliance_review(counselor_id):
    uid, role = authenticate(("ComplianceAuditor",))
    values = validate_body(body(), REVIEW_SPEC)
    counselor = get_counselor(counselor_id)

    prior = counselor.get("last_review_user_id")
    if prior is not None and prior == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    decision = values["decision"]
    sources, target = REVIEW_TRANSITIONS[decision]
    if counselor["incentive_eligibility"] not in sources:
        raise ApiError("ERR_COUNSELOR_INVALID_REVIEW_STATE")
    if decision == "APPROVE" and counselor["comp_plan_type"] == "NONE_ON_FILE":
        raise ApiError("ERR_COUNSELOR_INVALID_REVIEW_STATE")

    counselor["incentive_eligibility"] = target
    counselor["last_review_user_id"] = uid
    touch(counselor)
    return object_response(serializers.counselor(counselor))
