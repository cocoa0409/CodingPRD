"""Membership endpoints (PRD §3.1).

Enroll creates a Membership (status ACTIVE, started_at := current server time).
A customer may enroll/cancel only their own membership; a dispatcher may act on
any. Cancel moves status -> CANCELLED.
"""
from flask import Blueprint, request

import clock
import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_fields,
                     serialize, serialize_list, sort_by_created)
from middleware import get_identity, require_roles

bp = Blueprint("memberships", __name__)


@bp.post("/v1/memberships")
def enroll():
    user_id, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    body = get_json_body()
    require_fields(body, ["customer_id", "plan_id"])

    # Existence: body FKs resolved left-to-right (customer_id then plan_id).
    customer = db.customers.get(body["customer_id"])
    if customer is None:
        raise err("ERR_NOT_FOUND", "Customer not found")
    plan = db.membership_plans.get(body["plan_id"])
    if plan is None:
        raise err("ERR_NOT_FOUND", "Membership plan not found")

    # Ownership: a Customer may only enroll themselves.
    if role == "Customer" and customer["id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customers may only enroll themselves")

    record = {
        "customer_id": customer["id"],
        "plan_id": plan["id"],
        "status": "ACTIVE",
        "started_at": clock.now_iso(),
    }
    db.stamp_new(record)
    db.memberships[record["id"]] = record
    return response.object_response(serialize(record), 201)


@bp.get("/v1/memberships/<membership_id>")
def get_membership(membership_id):
    user_id, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    record = db.memberships.get(membership_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Membership not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/memberships")
def list_memberships():
    user_id, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    plan_id = request.args.get("plan_id")

    items = list(db.memberships.values())
    if customer_id is not None:
        items = [m for m in items if m["customer_id"] == customer_id]
    if plan_id is not None:
        items = [m for m in items if m["plan_id"] == plan_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)


@bp.post("/v1/memberships/<membership_id>/cancel")
def cancel_membership(membership_id):
    user_id, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    record = db.memberships.get(membership_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Membership not found")

    # Ownership: a Customer may cancel only their own membership.
    if role == "Customer" and record["customer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customers may only cancel their own membership")

    record["status"] = "CANCELLED"
    db.touch(record)
    return response.object_response(serialize(record), 200)
