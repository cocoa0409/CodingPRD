"""MembershipPlan endpoints (PRD §3.1).

Plan: name, tier (BASIC|PREMIER), monthly_fee_cents, labor_discount_pct (0..1),
waives_dispatch_fee (default false), priority_dispatch (default false).
"""
from flask import Blueprint

import db
import response
from errors import err
from helpers import (get_json_body, paginate, parse_pagination, require_bool,
                     require_enum, require_fields, require_nonneg_int,
                     require_number, require_string, serialize, serialize_list,
                     sort_by_created)
from middleware import get_identity, require_roles

bp = Blueprint("membership_plans", __name__)

TIERS = {"BASIC", "PREMIER"}


@bp.post("/v1/membership-plans")
def create_plan():
    _, role = get_identity()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["name", "tier", "monthly_fee_cents", "labor_discount_pct"])
    require_string(body["name"], "name")
    require_enum(body["tier"], TIERS, "tier")
    require_nonneg_int(body["monthly_fee_cents"], "monthly_fee_cents")
    require_number(body["labor_discount_pct"], "labor_discount_pct")
    pct = body["labor_discount_pct"]
    if pct < 0 or pct > 1:
        raise err("ERR_INVALID_REQUEST", "labor_discount_pct must be a fraction between 0 and 1")

    waives = body.get("waives_dispatch_fee", False)
    if waives is None:
        waives = False
    require_bool(waives, "waives_dispatch_fee")

    priority = body.get("priority_dispatch", False)
    if priority is None:
        priority = False
    require_bool(priority, "priority_dispatch")

    record = {
        "name": body["name"],
        "tier": body["tier"],
        "monthly_fee_cents": body["monthly_fee_cents"],
        "labor_discount_pct": pct,
        "waives_dispatch_fee": waives,
        "priority_dispatch": priority,
    }
    db.stamp_new(record)
    db.membership_plans[record["id"]] = record
    return response.object_response(serialize(record), 201)


@bp.get("/v1/membership-plans/<plan_id>")
def get_plan(plan_id):
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    record = db.membership_plans.get(plan_id)
    if record is None:
        raise err("ERR_NOT_FOUND", "Membership plan not found")
    return response.object_response(serialize(record), 200)


@bp.get("/v1/membership-plans")
def list_plans():
    _, role = get_identity()
    require_roles(role, {"Dispatcher", "Customer"})
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.membership_plans.values()))
    page, total = paginate(items, limit, offset)
    return response.array_response(serialize_list(page), limit, offset, total, 200)
