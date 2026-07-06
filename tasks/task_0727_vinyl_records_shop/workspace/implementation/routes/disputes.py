"""GradingDispute endpoints (cyclic state machine + regrade cascade)."""
from flask import Blueprint, request

import db
from models import base_fields, touch
from middleware import authenticate
from validators import (
    get_body, require_grade, get_pagination, paginate, sorted_by_created, lookup,
)
from response import success, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
)
from services import public, public_list, regrade_cascade

bp = Blueprint("disputes", __name__)


def _owner_check(role, user_id, customer_id):
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Customer does not own this resource")


@bp.route("/shop/grading-disputes", methods=["POST"])
def create_dispute():
    user_id, role = authenticate({"Customer"})
    body = get_body()
    inv_id = body.get("inventory_item_id")
    customer_id = body.get("customer_id")
    if not isinstance(inv_id, str) or not inv_id:
        raise err(ERR_INVALID_REQUEST, "inventory_item_id required")
    if not isinstance(customer_id, str) or not customer_id:
        raise err(ERR_INVALID_REQUEST, "customer_id required")
    claimed = require_grade(body, "claimed_grade")
    lookup(db.db.inventory_items, inv_id)
    lookup(db.db.customers, customer_id)
    _owner_check(role, user_id, customer_id)
    d = base_fields()
    d.update({
        "inventory_item_id": inv_id,
        "customer_id": customer_id,
        "claimed_grade": claimed,
        "status": "OPEN",
        "resolution_grade": None,
    })
    db.db.grading_disputes[d["id"]] = d
    return success(public(d), 201)


@bp.route("/shop/grading-disputes/<did>", methods=["GET"])
def read_dispute(did):
    authenticate({"Customer", "Grader", "Manager"})
    d = lookup(db.db.grading_disputes, did)
    return success(public(d), 200)


@bp.route("/shop/grading-disputes", methods=["GET"])
def list_disputes():
    authenticate({"Customer", "Grader", "Manager"})
    limit, offset = get_pagination()
    items = list(db.db.grading_disputes.values())
    for key in ("inventory_item_id", "customer_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/grading-disputes/<did>/start-review", methods=["POST"])
def start_review(did):
    authenticate({"Grader"})
    d = lookup(db.db.grading_disputes, did)
    if d["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Dispute is not OPEN")
    item = db.db.inventory_items.get(d["inventory_item_id"])
    if item is None or not item["is_used"]:
        raise err(ERR_INVALID_STATE, "Disputed copy must be used")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success(public(d), 200)


@bp.route("/shop/grading-disputes/<did>/request-info", methods=["POST"])
def request_info(did):
    authenticate({"Grader"})
    d = lookup(db.db.grading_disputes, did)
    if d["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Dispute is not UNDER_REVIEW")
    d["status"] = "NEEDS_INFO"
    touch(d)
    return success(public(d), 200)


@bp.route("/shop/grading-disputes/<did>/provide-info", methods=["POST"])
def provide_info(did):
    user_id, role = authenticate({"Customer"})
    d = lookup(db.db.grading_disputes, did)
    _owner_check(role, user_id, d["customer_id"])
    if d["status"] != "NEEDS_INFO":
        raise err(ERR_INVALID_STATE, "Dispute is not NEEDS_INFO")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success(public(d), 200)


@bp.route("/shop/grading-disputes/<did>/escalate", methods=["POST"])
def escalate(did):
    authenticate({"Grader"})
    d = lookup(db.db.grading_disputes, did)
    if d["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Dispute is not UNDER_REVIEW")
    d["status"] = "ESCALATED"
    touch(d)
    return success(public(d), 200)


@bp.route("/shop/grading-disputes/<did>/resolve-regrade", methods=["POST"])
def resolve_regrade(did):
    user_id, role = authenticate({"Grader", "Manager"})
    d = lookup(db.db.grading_disputes, did)
    # UNDER_REVIEW resolvable by Grader or Manager; ESCALATED only by Manager.
    if d["status"] == "UNDER_REVIEW":
        pass
    elif d["status"] == "ESCALATED":
        if role != "Manager":
            from errors import ERR_FORBIDDEN
            raise err(ERR_FORBIDDEN, "Only a Manager may resolve an escalated dispute")
    else:
        raise err(ERR_INVALID_STATE, "Dispute cannot be resolved from its current state")
    body = get_body()
    resolution = require_grade(body, "resolution_grade")
    d["resolution_grade"] = resolution
    d["status"] = "RESOLVED_REGRADE"
    touch(d)
    item = db.db.inventory_items.get(d["inventory_item_id"])
    if item is not None:
        regrade_cascade(item, resolution)
    return success(public(d), 200)


@bp.route("/shop/grading-disputes/<did>/resolve-uphold", methods=["POST"])
def resolve_uphold(did):
    user_id, role = authenticate({"Grader", "Manager"})
    d = lookup(db.db.grading_disputes, did)
    if d["status"] == "UNDER_REVIEW":
        pass
    elif d["status"] == "ESCALATED":
        if role != "Manager":
            from errors import ERR_FORBIDDEN
            raise err(ERR_FORBIDDEN, "Only a Manager may resolve an escalated dispute")
    else:
        raise err(ERR_INVALID_STATE, "Dispute cannot be resolved from its current state")
    d["status"] = "RESOLVED_UPHELD"
    touch(d)
    return success(public(d), 200)
