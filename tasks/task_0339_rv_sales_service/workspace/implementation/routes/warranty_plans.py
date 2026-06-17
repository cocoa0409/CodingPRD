"""Warranty plan routes (PRD 3.8)."""

from flask import Blueprint, request

import db
import errors
from common import (body, new_entity, touch, require_int, require_enum, opt_int,
                    paginate, get_or_404, find_dealership)
from middleware import get_auth, require_role
from response import ok, created, ok_list

bp = Blueprint("warranty_plans", __name__)

PLAN_KINDS = {"FACTORY", "EXTENDED"}


@bp.post("/warranty-plans")
def create_plan():
    _, role = get_auth()
    require_role(role, {"SalesAgent", "DealerManager"})
    data = body()
    did = data.get("dealership_id")
    find_dealership(did)
    unit = get_or_404("units", data.get("unit_id"))
    customer = get_or_404("customers", data.get("customer_id"))
    plan_kind = require_enum(data, "plan_kind", PLAN_KINDS)
    cap = require_int(data, "coverage_cap_cents", minimum=0)
    deductible = opt_int(data, "deductible_cents", default=0, minimum=0)
    rec = new_entity({
        "dealership_id": did,
        "unit_id": unit["id"],
        "customer_id": customer["id"],
        "plan_kind": plan_kind,
        "coverage_cap_cents": cap,
        "deductible_cents": deductible,
        "consumed_cents": 0,
        "status": "ACTIVE",
    })
    db.store["warranty_plans"][rec["id"]] = rec
    return created(rec)


@bp.get("/warranty-plans")
def list_plans():
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    items = list(db.store["warranty_plans"].values())
    a = request.args
    for field in ("dealership_id", "unit_id", "customer_id", "status"):
        val = a.get(field)
        if val is not None:
            items = [p for p in items if p.get(field) == val]
    page, limit, offset, total = paginate(items)
    return ok_list(page, limit, offset, total)


@bp.get("/warranty-plans/<plan_id>")
def get_plan(plan_id):
    user_id, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor", "Customer"})
    rec = get_or_404("warranty_plans", plan_id)
    if role == "Customer" and rec["customer_id"] != user_id:
        errors.err("ERR_WARRANTY_PLAN_NOT_FOUND", "Warranty plan not found.")
    return ok(rec)


@bp.post("/warranty-plans/<plan_id>/cancel")
def cancel_plan(plan_id):
    _, role = get_auth()
    require_role(role, {"DealerManager"})
    rec = get_or_404("warranty_plans", plan_id)
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok(rec)
