"""Rescue plans and revision lineage (PRD section 3.2)."""

from flask import Blueprint, request

import db
import serializers
from errors import ERR_PLAN_INVALID_STATE, ERR_PLAN_NOT_FOUND, raise_error
from helpers import (
    body, list_response, opt_enum_array, reject_unknown, req_enum, req_int,
    iso_z, now_dt, stamp_new, touch,
)
from middleware import ALL_ROLES, require_auth
from response import success_object
from routes.personnel import CERTIFICATIONS
from routes.spaces import check_expected_space_version, get_space

bp = Blueprint("plans", __name__)

RETRIEVAL_SYSTEM_TYPES = ("MECHANICAL_RETRIEVAL", "TRIPOD", "HORIZONTAL_HAUL", "ENTRY_RESCUE")


def get_plan(plan_id):
    plan = db.rescue_plans.get(plan_id)
    if plan is None:
        raise_error(ERR_PLAN_NOT_FOUND, "Rescue plan not found")
    return plan


@bp.route("/rescue-ops/confined-spaces/<space_id>/rescue-plans", methods=["POST"])
def create_plan(space_id):
    user_id, _, _ = require_auth(("RescueTeamLead",))
    space = get_space(space_id)
    data = body()
    reject_unknown(data, {
        "required_team_size", "required_certifications", "retrieval_system_type",
        "expected_space_version",
    })
    required_team_size = req_int(data, "required_team_size")
    if required_team_size < 0:
        raise_error(("ERR_INVALID_REQUEST", 400), "required_team_size must be non-negative")
    required_certifications = opt_enum_array(data, "required_certifications", CERTIFICATIONS, [])
    retrieval_system_type = req_enum(data, "retrieval_system_type", RETRIEVAL_SYSTEM_TYPES)
    check_expected_space_version(data, space)
    prior_revisions = [p["plan_revision"] for p in db.rescue_plans.values()
                       if p["space_id"] == space["id"]]
    plan = {
        "space_id": space["id"],
        "required_team_size": required_team_size,
        "required_certifications": required_certifications,
        "retrieval_system_type": retrieval_system_type,
        "plan_revision": (max(prior_revisions) + 1) if prior_revisions else 1,
        "status": "DRAFT",
        "approved_by": None,
        "approved_at": None,
    }
    stamp_new(plan)
    db.rescue_plans[plan["id"]] = plan
    # Creating a plan supersedes existing DRAFT plans of the same space.
    for other in db.rescue_plans.values():
        if other["space_id"] == space["id"] and other["id"] != plan["id"] \
                and other["status"] == "DRAFT":
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(space)
    return success_object(serializers.rescue_plan(plan), 201)


@bp.route("/rescue-ops/rescue-plans", methods=["GET"])
def list_plans():
    require_auth(ALL_ROLES)
    return list_response(list(db.rescue_plans.values()), serializers.rescue_plan, {
        "space_id": request.args.get("space_id"),
        "status": request.args.get("status"),
        "approved_by": request.args.get("approved_by"),
    })


@bp.route("/rescue-ops/rescue-plans/<plan_id>", methods=["GET"])
def get_one_plan(plan_id):
    require_auth(ALL_ROLES)
    return success_object(serializers.rescue_plan(get_plan(plan_id)))


@bp.route("/rescue-ops/rescue-plans/<plan_id>/approve", methods=["POST"])
def approve_plan(plan_id):
    user_id, _, _ = require_auth(("RescueTeamLead",))
    plan = get_plan(plan_id)
    data = body()
    reject_unknown(data, {"expected_space_version"})
    space = get_space(plan["space_id"])
    check_expected_space_version(data, space)  # OCC (412) precedes state checks
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_INVALID_STATE, "Only a DRAFT plan can be approved")
    plan["status"] = "APPROVED"
    plan["approved_by"] = user_id
    plan["approved_at"] = iso_z(now_dt())
    touch(plan)
    # Approve supersedes any *other* APPROVED plan of the same space.
    for other in db.rescue_plans.values():
        if other["space_id"] == space["id"] and other["id"] != plan["id"] \
                and other["status"] == "APPROVED":
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(space)
    return success_object(serializers.rescue_plan(plan))
