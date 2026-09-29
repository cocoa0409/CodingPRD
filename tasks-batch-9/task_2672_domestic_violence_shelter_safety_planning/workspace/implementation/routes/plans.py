"""SafetyPlan and PlanComponent endpoints."""

from flask import Blueprint

from db import db, public, touch
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOTLINE_ADVOCATE, ROLE_HOUSING_SPECIALIST,
                        ROLE_SHELTER_MANAGER, acting_staff_id, auth)
from response import created, ok
from routes.common import (by_created, filtered, get_assessment, get_client, get_component,
                           get_plan, insert, list_page)
from services import calc, cascade, derive
from validation import (date_out, get_body, q_enum, q_str, req_date, req_enum, req_int,
                        req_str)

bp = Blueprint("plans", __name__)

PLAN_STATUSES = ("DRAFT", "ACTIVE", "UNDER_REVISION", "ARCHIVED")
COMPONENT_STATUSES = ("DRAFT", "IMPLEMENTED", "REVIEW_REQUIRED", "BLOCKED")
READ_ROLES = (ROLE_HOTLINE_ADVOCATE, ROLE_SHELTER_MANAGER, ROLE_HOUSING_SPECIALIST,
              ROLE_AGENCY_ADMIN)


def _require_author(plan, user_id, role):
    """Only the plan's author may work the plan; an AgencyAdmin identity never matches."""
    actor = acting_staff_id(user_id, role)
    if actor is None or plan["authored_by_staff_id"] != actor:
        raise ApiError("ERR_NOT_PLAN_AUTHOR")


@bp.post("/safety-plans")
def create_plan():
    user_id, role = auth((ROLE_HOTLINE_ADVOCATE,))
    body = get_body()
    client_id = req_str(body, "client_id")
    assessment_id = req_str(body, "based_on_risk_assessment_id")
    expected_client_version = req_int(body, "expected_client_version", 0)

    client = get_client(client_id)
    assessment = get_assessment(assessment_id)

    call = db.hotline_calls.get(assessment["hotline_call_id"])
    if call is None or call["client_id"] != client["id"]:
        raise ApiError("ERR_CROSS_REFERENCE_MISMATCH",
                       "the risk assessment belongs to a different client")

    if expected_client_version != client["version"]:
        raise ApiError("ERR_STALE_CLIENT_VERSION")

    plan = insert("safety_plans", {
        "client_id": client["id"],
        "based_on_risk_assessment_id": assessment["id"],
        "authored_by_staff_id": acting_staff_id(user_id, role),
        "superseded_by_plan_id": None,
        "status": "DRAFT",
        "coverage_score": 0.0,
        "revision_count": 0,
        "archived_at": None,
    })
    if cascade.archive_live_plans(client, plan):
        cascade.reject_open_referrals(client)
    touch(client)
    return created(public(plan))


@bp.get("/safety-plans/<plan_id>")
def read_plan(plan_id):
    auth(READ_ROLES)
    return ok(public(get_plan(plan_id)))


@bp.get("/safety-plans")
def list_plans():
    auth(READ_ROLES)
    filters = {
        "client_id": q_str("client_id"),
        "based_on_risk_assessment_id": q_str("based_on_risk_assessment_id"),
        "authored_by_staff_id": q_str("authored_by_staff_id"),
        "superseded_by_plan_id": q_str("superseded_by_plan_id"),
        "status": q_enum("status", PLAN_STATUSES),
    }
    return list_page(by_created(filtered("safety_plans", filters)))


@bp.post("/safety-plans/<plan_id>/components")
def create_component(plan_id):
    user_id, role = auth((ROLE_HOTLINE_ADVOCATE,))
    plan = get_plan(plan_id)
    _require_author(plan, user_id, role)
    body = get_body()
    component_type = req_enum(body, "component_type", calc.COMPONENT_TYPES)
    detail = req_str(body, "detail", 1, 2000)
    target_completion_date = req_date(body, "target_completion_date")

    for existing in derive.plan_components(plan["id"]):
        if existing["component_type"] == component_type:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "this plan already carries a component of that type")

    component = insert("plan_components", {
        "safety_plan_id": plan["id"],
        "component_type": component_type,
        "detail": detail,
        "target_completion_date": date_out(target_completion_date),
        "status": "DRAFT",
        "weight_effective": 0.0,
        "subscore": 0.0,
    })
    derive.recompute_plan_coverage(plan)
    touch(plan)
    return created(public(component))


@bp.get("/safety-plans/<plan_id>/components")
def list_components(plan_id):
    auth(READ_ROLES)
    plan = get_plan(plan_id)
    filters = {
        "safety_plan_id": plan["id"],
        "component_type": q_enum("component_type", calc.COMPONENT_TYPES),
        "status": q_enum("status", COMPONENT_STATUSES),
    }
    return list_page(by_created(filtered("plan_components", filters)))


@bp.post("/safety-plans/<plan_id>/components/<component_id>/implement")
def implement_component(plan_id, component_id):
    user_id, role = auth((ROLE_HOTLINE_ADVOCATE,))
    plan = get_plan(plan_id)
    _require_author(plan, user_id, role)
    component = get_component(plan, component_id)

    status = component["status"]
    if status == "IMPLEMENTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the component is already IMPLEMENTED")
    if status == "DRAFT" and plan["status"] not in ("DRAFT", "ACTIVE", "UNDER_REVISION"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "the owning plan is not in a workable status")
    if status == "BLOCKED":
        client = db.clients.get(plan["client_id"])
        if client is not None and client["confidentiality_posture"] == "SEALED":
            raise ApiError("ERR_CONFIDENTIALITY_HOLD")

    component["status"] = "IMPLEMENTED"
    touch(component)
    derive.recompute_plan_coverage(plan)
    touch(plan)
    return ok(public(component))


@bp.post("/safety-plans/<plan_id>/activate")
def activate_plan(plan_id):
    user_id, role = auth((ROLE_HOTLINE_ADVOCATE,))
    plan = get_plan(plan_id)
    _require_author(plan, user_id, role)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", "only a DRAFT plan may be activated")
    if not derive.plan_components(plan["id"]):
        raise ApiError("ERR_PLAN_HAS_NO_COMPONENTS")

    plan["status"] = "ACTIVE"
    touch(plan)
    derive.recompute_plan_coverage(plan)
    return ok(public(plan))


@bp.post("/safety-plans/<plan_id>/revise")
def revise_plan(plan_id):
    user_id, role = auth((ROLE_HOTLINE_ADVOCATE,))
    plan = get_plan(plan_id)
    _require_author(plan, user_id, role)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an ACTIVE plan may be suspended for revision")

    plan["status"] = "UNDER_REVISION"
    touch(plan)
    client = db.clients.get(plan["client_id"])
    if client is not None:
        cascade.reject_open_referrals(client)
    derive.recompute_plan_coverage(plan)
    return ok(public(plan))


@bp.post("/safety-plans/<plan_id>/reactivate")
def reactivate_plan(plan_id):
    user_id, role = auth((ROLE_HOTLINE_ADVOCATE,))
    plan = get_plan(plan_id)
    _require_author(plan, user_id, role)
    if plan["status"] != "UNDER_REVISION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only an UNDER_REVISION plan may be returned to service")
    if any(c["status"] == "BLOCKED" for c in derive.plan_components(plan["id"])):
        raise ApiError("ERR_PLAN_HAS_BLOCKED_COMPONENT")

    plan["status"] = "ACTIVE"
    plan["revision_count"] = plan["revision_count"] + 1
    touch(plan)
    derive.recompute_plan_coverage(plan)
    return ok(public(plan))
