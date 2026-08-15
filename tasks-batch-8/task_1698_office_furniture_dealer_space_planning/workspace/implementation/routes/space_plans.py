"""SpacePlan and Typical routes: plan revision cycle with version pinning."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_STATE, ERR_DUPLICATE_REFERENCE
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import get_or_404, new_entity, touch, plan_budget_recompute
from validate import body_dict, req_str, req_int, opt_int

bp = Blueprint("space_plans", __name__)

EDITABLE_PLAN_STATES = {"DRAFT", "IN_REVISION"}


@bp.route("/api/space-plans", methods=["POST"])
def create_plan():
    authorize(["Designer"])
    body = body_dict()
    customer_id = req_str(body, "customer_id")
    name = req_str(body, "name")
    supersedes_plan_id = body.get("supersedes_plan_id")
    if supersedes_plan_id is not None and not isinstance(supersedes_plan_id, str):
        from errors import ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "supersedes_plan_id must be a string")
    get_or_404("customers", customer_id)
    if supersedes_plan_id is not None:
        get_or_404("space_plans", supersedes_plan_id)
    plan = new_entity("space_plans", {
        "customer_id": customer_id,
        "name": name,
        "revision_no": 1,
        "supersedes_plan_id": supersedes_plan_id,
        "approved_version": None,
        "budget_cents": 0,
        "status": "DRAFT",
    })
    return success_object(public(plan), status=201)


@bp.route("/api/space-plans", methods=["GET"])
def list_plans():
    authorize(ALL_ROLES)
    return list_response("space_plans", ["customer_id", "status", "supersedes_plan_id"])


@bp.route("/api/space-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    authorize(ALL_ROLES)
    return get_response("space_plans", plan_id)


@bp.route("/api/space-plans/<plan_id>/submit", methods=["POST"])
def submit_plan(plan_id):
    authorize(["Designer"])
    plan = get_or_404("space_plans", plan_id)
    if plan["status"] not in ("DRAFT", "IN_REVISION"):
        raise_error(ERR_INVALID_STATE, f"cannot submit a plan in status {plan['status']}")
    typicals = [t for t in db["typicals"].values() if t["space_plan_id"] == plan_id]
    if not typicals:
        raise_error(ERR_INVALID_STATE, "a plan requires at least one typical before submit")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return success_object(public(plan))


@bp.route("/api/space-plans/<plan_id>/approve", methods=["POST"])
def approve_plan(plan_id):
    authorize(["ClientApprover"])
    plan = get_or_404("space_plans", plan_id)
    if plan["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"cannot approve a plan in status {plan['status']}")
    plan["status"] = "APPROVED"
    # version-pinning anchor: approved_version equals the post-approval version
    touch(plan)
    plan["approved_version"] = plan["version"]
    pred_id = plan.get("supersedes_plan_id")
    if pred_id:
        predecessor = db["space_plans"].get(pred_id)
        if predecessor is not None and predecessor["status"] == "APPROVED":
            predecessor["status"] = "SUPERSEDED"
            touch(predecessor)
    return success_object(public(plan))


@bp.route("/api/space-plans/<plan_id>/revise", methods=["POST"])
def revise_plan(plan_id):
    authorize(["Designer"])
    plan = get_or_404("space_plans", plan_id)
    if plan["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, f"cannot revise a plan in status {plan['status']}")
    plan["status"] = "IN_REVISION"
    plan["revision_no"] = int(plan.get("revision_no", 1)) + 1
    plan["approved_version"] = None
    touch(plan)
    return success_object(public(plan))


# ---------------------------------------------------------------------------
# Typicals
# ---------------------------------------------------------------------------

@bp.route("/api/typicals", methods=["POST"])
def create_typical():
    authorize(["Designer"])
    body = body_dict()
    space_plan_id = req_str(body, "space_plan_id")
    code = req_str(body, "code")
    quantity = req_int(body, "quantity", minv=1)
    per_instance = req_int(body, "target_budget_cents_per_instance", minv=0)
    plan = get_or_404("space_plans", space_plan_id)
    # priority 4: typicals editable only while DRAFT or IN_REVISION
    if plan["status"] not in EDITABLE_PLAN_STATES:
        raise_error(ERR_INVALID_STATE, f"cannot add typicals to a plan in status {plan['status']}")
    # priority 8c: code unique within the plan
    for other in db["typicals"].values():
        if other["space_plan_id"] == space_plan_id and other["code"] == code:
            raise_error(ERR_DUPLICATE_REFERENCE, f"typical code '{code}' already exists in plan {space_plan_id}")
    typical = new_entity("typicals", {
        "space_plan_id": space_plan_id,
        "code": code,
        "quantity": quantity,
        "target_budget_cents_per_instance": per_instance,
        "extended_budget_cents": quantity * per_instance,
    })
    plan_budget_recompute(plan)
    return success_object(public(typical), status=201)


@bp.route("/api/typicals", methods=["GET"])
def list_typicals():
    authorize(ALL_ROLES)
    return list_response("typicals", ["space_plan_id"])


@bp.route("/api/typicals/<typical_id>", methods=["GET"])
def get_typical(typical_id):
    authorize(ALL_ROLES)
    return get_response("typicals", typical_id)


@bp.route("/api/typicals/<typical_id>", methods=["PATCH"])
def patch_typical(typical_id):
    authorize(["Designer"])
    typical = get_or_404("typicals", typical_id)
    plan = get_or_404("space_plans", typical["space_plan_id"])
    # priority 4: editable only while the plan is DRAFT or IN_REVISION
    if plan["status"] not in EDITABLE_PLAN_STATES:
        raise_error(ERR_INVALID_STATE, f"cannot edit typicals of a plan in status {plan['status']}")
    body = body_dict()
    if "quantity" in body and body["quantity"] is not None:
        typical["quantity"] = req_int(body, "quantity", minv=1)
    if "target_budget_cents_per_instance" in body and body["target_budget_cents_per_instance"] is not None:
        typical["target_budget_cents_per_instance"] = req_int(body, "target_budget_cents_per_instance", minv=0)
    typical["extended_budget_cents"] = typical["quantity"] * typical["target_budget_cents_per_instance"]
    touch(typical)
    plan_budget_recompute(plan)
    return success_object(public(typical))
