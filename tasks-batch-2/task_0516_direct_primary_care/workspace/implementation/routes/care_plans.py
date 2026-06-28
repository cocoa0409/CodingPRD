"""CarePlan endpoints with cyclic revision loop (PRD §3.10)."""
from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from middleware import authenticate, require_roles
from routes.helpers import get_or_404

bp = Blueprint("care_plans", __name__)


@bp.route("/care-plans", methods=["POST"])
def create_care_plan():
    caller = authenticate()
    require_roles(caller, {"Provider"})
    data = validate.body()

    member_id = validate.require(data, "member_id", str)
    origin_visit_id = validate.require(data, "origin_visit_id", str)
    goal_count = validate.optional(data, "goal_count", int, 0)

    member = get_or_404("member", member_id)
    visit = get_or_404("visit", origin_visit_id)

    # Provider ownership: provider must be the member's assigned PCP.
    if caller.role == "Provider" and member.get("assigned_provider_id") != caller.user_id:
        raise errors.forbidden("Provider does not own this member.")

    if goal_count < 0:
        raise errors.validation("goal_count must be >= 0.")

    e = dict(db.common_fields())
    e["id"] = db.new_id()
    e["_seq"] = db.next_seq()
    e["member_id"] = member_id
    e["origin_visit_id"] = origin_visit_id
    e["plan_status"] = "DRAFT"
    e["goal_count"] = goal_count
    e["revision_number"] = 0
    db.care_plans[e["id"]] = e
    return response.object_response(serialize.care_plan(e), 201)


@bp.route("/care-plans/<cid>", methods=["GET"])
def get_care_plan(cid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    e = get_or_404("care_plan", cid)
    _read_ownership(caller, e)
    return response.object_response(serialize.care_plan(e), 200)


@bp.route("/care-plans", methods=["GET"])
def list_care_plans():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    limit, offset = validate.pagination()
    member_id = request.args.get("member_id")
    origin_visit_id = request.args.get("origin_visit_id")

    rows = list(db.care_plans.values())
    if caller.role == "Member":
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    elif caller.role == "Provider":
        rows = [r for r in rows
                if db.members.get(r["member_id"], {}).get("assigned_provider_id") == caller.user_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if origin_visit_id is not None:
        rows = [r for r in rows if r["origin_visit_id"] == origin_visit_id]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.care_plan(r) for r in page], limit, offset, total, 200
    )


@bp.route("/care-plans/<cid>", methods=["PATCH"])
def patch_care_plan(cid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    e = get_or_404("care_plan", cid)
    _provider_owns(caller, e)
    data = validate.body()
    goal_count = validate.require(data, "goal_count", int)
    if goal_count < 0:
        raise errors.validation("goal_count must be >= 0.")

    # Editable only while DRAFT or UNDER_REVISION (PRD §3.10).
    if e["plan_status"] not in ("DRAFT", "UNDER_REVISION"):
        raise errors.invalid_state("Care plan is not editable in %s." % e["plan_status"])

    e["goal_count"] = goal_count
    db.touch(e)
    return response.object_response(serialize.care_plan(e), 200)


@bp.route("/care-plans/<cid>/activate", methods=["POST"])
def activate_care_plan(cid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    e = get_or_404("care_plan", cid)
    _provider_owns(caller, e)

    # State (priority 5): activate defined from DRAFT or UNDER_REVISION.
    if e["plan_status"] not in ("DRAFT", "UNDER_REVISION"):
        raise errors.invalid_state("Care plan cannot be activated from %s." % e["plan_status"])

    # Business: goal_count >= 1 (priority 13).
    if e["goal_count"] < 1:
        raise errors.care_plan_empty("Care plan must have at least one goal to activate.")

    # Cross-entity (priority 7): only the DRAFT->ACTIVE transition requires the
    # origin visit to be a COMPLETED ANNUAL_PHYSICAL (§1.2).
    if e["plan_status"] == "DRAFT":
        visit = db.visits.get(e["origin_visit_id"])
        if visit is None or visit["clinical_status"] != "COMPLETED" \
                or visit["visit_type"] != "ANNUAL_PHYSICAL":
            raise errors.member_not_eligible(
                "Origin visit must be a completed annual physical."
            )

    e["plan_status"] = "ACTIVE"
    db.touch(e)
    return response.object_response(serialize.care_plan(e), 200)


@bp.route("/care-plans/<cid>/reopen", methods=["POST"])
def reopen_care_plan(cid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    e = get_or_404("care_plan", cid)
    _provider_owns(caller, e)

    if e["plan_status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE plan can be reopened.")

    e["revision_number"] = e["revision_number"] + 1
    e["plan_status"] = "UNDER_REVISION"
    db.touch(e)
    return response.object_response(serialize.care_plan(e), 200)


@bp.route("/care-plans/<cid>/archive", methods=["POST"])
def archive_care_plan(cid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    e = get_or_404("care_plan", cid)
    _provider_owns(caller, e)

    if e["plan_status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE plan can be archived.")

    e["plan_status"] = "ARCHIVED"
    db.touch(e)
    return response.object_response(serialize.care_plan(e), 200)


def _read_ownership(caller, plan):
    if caller.role == "Member" and caller.user_id != plan["member_id"]:
        raise errors.forbidden("Member does not own this care plan.")
    if caller.role == "Provider":
        member = db.members.get(plan["member_id"])
        if member is None or member.get("assigned_provider_id") != caller.user_id:
            raise errors.forbidden("Provider does not own this care plan.")


def _provider_owns(caller, plan):
    if caller.role == "Provider":
        member = db.members.get(plan["member_id"])
        if member is None or member.get("assigned_provider_id") != caller.user_id:
            raise errors.forbidden("Provider does not own this care plan.")
