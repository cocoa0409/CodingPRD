"""TopDownAllocation endpoints."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_string,
                  req_int, find_or_404, paginate, stamp_new, touch)
from services import calc

bp = Blueprint("allocations", __name__)

ADMIN = ("SalesOpsAdmin",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")


@bp.route("/sales-planning/allocations", methods=["POST"])
def create_allocation():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id", "scope_territory_id", "pool_cents"})
    require_fields(body, ["plan_year_id", "scope_territory_id", "pool_cents"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")
    scope = find_or_404(store.territories, body["scope_territory_id"], "scope territory")
    pool = req_int(body, "pool_cents")

    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] != "OPEN":
        raise ApiError("ERR_PLAN_NOT_OPEN", "Allocation creation requires plan status OPEN", 409)
    if scope["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "scope_territory_id belongs to a different plan year", 409)
    if pool <= 0:
        raise ApiError("ERR_AMOUNT_NOT_POSITIVE", "pool_cents must be > 0", 422)

    al = stamp_new({
        "plan_year_id": plan["id"],
        "scope_territory_id": scope["id"],
        "pool_cents": pool,
        "status": "DRAFT",
        "results": None,
    })
    store.allocations[al["id"]] = al
    return success_object(calc.ser_allocation(al), status=201)


@bp.route("/sales-planning/allocations", methods=["GET"])
def list_allocations():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.allocations.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [a for a in items if a["plan_year_id"] == v]
    if (v := request.args.get("scope_territory_id")) is not None:
        items = [a for a in items if a["scope_territory_id"] == v]
    if (v := request.args.get("status")) is not None:
        items = [a for a in items if a["status"] == v]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_allocation(a) for a in page], limit, offset, total)


@bp.route("/sales-planning/allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    al = find_or_404(store.allocations, aid, "allocation")
    return success_object(calc.ser_allocation(al))


@bp.route("/sales-planning/allocations/<aid>/apply", methods=["POST"])
def apply_allocation(aid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    al = find_or_404(store.allocations, aid, "allocation")
    body = get_body()
    reject_unknown_fields(body, {"expected_plan_year_version"})
    plan = find_or_404(store.plan_years, al["plan_year_id"], "plan year")

    # Tier 4: plan gate — OPEN required
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] != "OPEN":
        raise ApiError("ERR_PLAN_NOT_OPEN", "Allocation apply requires plan status OPEN", 409)

    # OCC
    if "expected_plan_year_version" not in body or body["expected_plan_year_version"] is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "expected_plan_year_version is required", 400)
    expected = req_int(body, "expected_plan_year_version")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_plan_year_version does not match the plan's current version", 412)

    # From-state
    if al["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot apply allocation in status {al['status']}", 409)

    scope = find_or_404(store.territories, al["scope_territory_id"], "scope territory")
    if scope["status"] != "ACTIVE":
        raise ApiError("ERR_TERRITORY_NOT_ACTIVE", "Scope territory is not ACTIVE", 409)

    # Pool agreement
    if scope["parent_territory_id"] is None:
        if al["pool_cents"] != plan["company_target_cents"]:
            raise ApiError("ERR_POOL_MISMATCH",
                           "pool_cents must equal company_target_cents on a root scope", 409)
    else:
        if scope["assigned_quota_cents"] is None or al["pool_cents"] != scope["assigned_quota_cents"]:
            raise ApiError("ERR_POOL_MISMATCH",
                           "pool_cents must equal the scope's assigned_quota_cents", 409)

    # Distribute over ACTIVE children
    children = calc._children_of(scope["id"], status="ACTIVE")
    shares = calc.allocation_largest_remainder(al["pool_cents"], children)

    # Supersede prior APPLIED runs on the same scope
    for other in store.allocations.values():
        if (other["id"] != al["id"] and other["scope_territory_id"] == scope["id"]
                and other["status"] == "APPLIED"):
            other["status"] = "SUPERSEDED"
            touch(other)

    al["status"] = "APPLIED"
    al["results"] = [{"territory_id": c["id"], "allocated_cents": amt}
                     for c, amt in shares]
    touch(al)

    # Write quotas: scope + each ACTIVE child
    scope["assigned_quota_cents"] = al["pool_cents"]
    touch(scope)
    for c, amt in shares:
        c["assigned_quota_cents"] = amt
        touch(c)

    # Cascade hop 2/3 on scope and children
    affected_ids = [scope["id"]] + [c["id"] for c in children]
    calc.recompute_territory_assignment_cascade(affected_ids)

    touch(plan)
    return success_object(calc.ser_allocation(al))


@bp.route("/sales-planning/allocations/<aid>/discard", methods=["POST"])
def discard_allocation(aid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    al = find_or_404(store.allocations, aid, "allocation")
    plan = find_or_404(store.plan_years, al["plan_year_id"], "plan year")
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] != "OPEN":
        raise ApiError("ERR_PLAN_NOT_OPEN", "Allocation discard requires plan status OPEN", 409)
    if al["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot discard allocation in status {al['status']}", 409)
    al["status"] = "DISCARDED"
    touch(al)
    return success_object(calc.ser_allocation(al))
