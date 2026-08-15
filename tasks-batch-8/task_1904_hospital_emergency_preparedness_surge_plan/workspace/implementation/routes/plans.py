"""Plan revision (emergency operations plan update cycle) endpoints."""

from flask import Blueprint, g, request

from db import clock, store
from domain import get_or_404, list_response, ser_plan
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import field_dt, field_str, new_entity, require_body, touch

bp = Blueprint("plans", __name__)


@bp.post("/plan-revisions")
@authorize(["EmergencyManager"])
def create_plan():
    body = require_body()
    revision_label = field_str(body, "revision_label", required=True)
    change_summary = field_str(body, "change_summary", required=True)
    effective_date = field_dt(body, "effective_date", required=True)
    supersedes_revision_id = field_str(body, "supersedes_revision_id")
    source_hva_id = field_str(body, "source_hva_id")

    supersedes_target = None
    if supersedes_revision_id is not None:
        supersedes_target = get_or_404("plan_revisions", supersedes_revision_id)
    if source_hva_id is not None:
        get_or_404("hazard_assessments", source_hva_id)

    if supersedes_target is not None and supersedes_target["status"] != "APPROVED":
        raise ApiError("ERR_SUPERSEDE_TARGET_NOT_APPROVED", 422,
                       "supersedes_revision_id must reference an APPROVED revision")

    plan = new_entity()
    plan.update({
        "revision_label": revision_label,
        "change_summary": change_summary,
        "effective_date": effective_date,
        "supersedes_revision_id": supersedes_revision_id,
        "source_hva_id": source_hva_id,
        "status": "DRAFT",
        "created_by_id": g.user_id,
        "approved_by_id": None,
        "approved_at": None,
    })
    store["plan_revisions"][plan["id"]] = plan
    return success(ser_plan(plan), "object", 201)


@bp.get("/plan-revisions")
@authorize(ALL_ROLES)
def list_plans():
    supersedes = request.args.get("supersedes_revision_id")
    source_hva = request.args.get("source_hva_id")
    status = request.args.get("status")

    def predicate(p):
        if supersedes is not None and p["supersedes_revision_id"] != supersedes:
            return False
        if source_hva is not None and p["source_hva_id"] != source_hva:
            return False
        if status is not None and p["status"] != status:
            return False
        return True

    return list_response("plan_revisions", ser_plan, predicate)


@bp.get("/plan-revisions/<plan_id>")
@authorize(ALL_ROLES)
def get_plan(plan_id):
    return success(ser_plan(get_or_404("plan_revisions", plan_id)), "object", 200)


@bp.post("/plan-revisions/<plan_id>/submit-review")
@authorize(["EmergencyManager"])
def submit_plan(plan_id):
    plan = get_or_404("plan_revisions", plan_id)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a DRAFT revision can be submitted for review")
    plan["status"] = "IN_REVIEW"
    touch(plan)
    return success(ser_plan(plan), "object", 200)


@bp.post("/plan-revisions/<plan_id>/approve")
@authorize(["HospitalAdministrator"])
def approve_plan(plan_id):
    plan = get_or_404("plan_revisions", plan_id)

    # Segregation of duties (priority 6) is evaluated before the state guard.
    if g.user_id == plan["created_by_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "the approver may not be the revision's creator")
    if plan["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an IN_REVIEW revision can be approved")
    for other in store["plan_revisions"].values():
        if (other["id"] != plan["id"] and other["status"] == "APPROVED"
                and other["id"] != plan["supersedes_revision_id"]):
            raise ApiError("ERR_OTHER_PLAN_APPROVED", 409,
                           "another plan revision is currently APPROVED")

    if plan["supersedes_revision_id"] is not None:
        predecessor = store["plan_revisions"].get(plan["supersedes_revision_id"])
        if predecessor is not None and predecessor["status"] == "APPROVED":
            predecessor["status"] = "SUPERSEDED"
            touch(predecessor)

    plan["status"] = "APPROVED"
    plan["approved_by_id"] = g.user_id
    plan["approved_at"] = clock.now()
    touch(plan)
    return success(ser_plan(plan), "object", 200)


@bp.post("/plan-revisions/<plan_id>/reject")
@authorize(["HospitalAdministrator"])
def reject_plan(plan_id):
    plan = get_or_404("plan_revisions", plan_id)
    if plan["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an IN_REVIEW revision can be rejected")
    plan["status"] = "DRAFT"
    touch(plan)
    return success(ser_plan(plan), "object", 200)
