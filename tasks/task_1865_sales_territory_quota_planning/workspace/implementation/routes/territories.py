"""Territory endpoints."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_string,
                  opt_string, req_int, opt_int, find_or_404, paginate,
                  stamp_new, touch)
from services import calc

bp = Blueprint("territories", __name__)

ADMIN = ("SalesOpsAdmin",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")


def _plan_gate_config_mutation(plan, reparenting=False):
    """Territory config mutation gate: plan LOCKED -> ERR_PLAN_LOCKED;
    re-parenting allowed only while DRAFT; other edits while DRAFT|OPEN."""
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if reparenting:
        if plan["status"] != "DRAFT":
            raise ApiError("ERR_PLAN_NOT_OPEN",
                           "Re-parenting requires plan status DRAFT", 409)
    else:
        if plan["status"] not in ("DRAFT", "OPEN"):
            raise ApiError("ERR_PLAN_NOT_OPEN",
                           "Operation requires plan status DRAFT or OPEN", 409)


def _check_cycle(territory_id, new_parent_id):
    """Walk up from new_parent; if we reach territory_id, it's a cycle."""
    cur = new_parent_id
    seen = set()
    while cur is not None:
        if cur == territory_id:
            raise ApiError("ERR_TERRITORY_CYCLE",
                           "Re-parenting would place the territory under itself or a descendant", 409)
        if cur in seen:
            break
        seen.add(cur)
        parent = store.territories.get(cur)
        if parent is None:
            break
        cur = parent.get("parent_territory_id")


@bp.route("/sales-planning/territories", methods=["POST"])
def create_territory():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id", "name", "potential_cents",
                                 "headcount_capacity", "parent_territory_id"})
    require_fields(body, ["plan_year_id", "name", "potential_cents", "headcount_capacity"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")
    name = req_string(body, "name")
    potential = req_int(body, "potential_cents", min_value=0)
    capacity = req_int(body, "headcount_capacity", min_value=1)
    parent_id = body.get("parent_territory_id")

    # Tier 4: create allowed any time before LOCKED
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)

    # Tier 3 body FK + Tier 5 cross-plan
    if parent_id is not None:
        if not isinstance(parent_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "parent_territory_id must be a string", 400)
        parent = find_or_404(store.territories, parent_id, "parent territory")
        if parent["plan_year_id"] != plan["id"]:
            raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                           "Parent territory belongs to a different plan year", 409)
        _check_cycle(None, parent_id)  # no-op for create (new id unknown); keeps helper honest

    terr = stamp_new({
        "plan_year_id": plan["id"],
        "parent_territory_id": parent_id,
        "name": name,
        "potential_cents": potential,
        "headcount_capacity": capacity,
        "assigned_quota_cents": None,
        "final_quota_cents": None,
        "status": "DRAFT",
    })
    store.territories[terr["id"]] = terr
    return success_object(calc.ser_territory(terr), status=201)


@bp.route("/sales-planning/territories", methods=["GET"])
def list_territories():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.territories.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [t for t in items if t["plan_year_id"] == v]
    if (v := request.args.get("parent_territory_id")) is not None:
        items = [t for t in items if t.get("parent_territory_id") == v]
    if (v := request.args.get("status")) is not None:
        items = [t for t in items if t["status"] == v]
    items.sort(key=lambda t: (t["created_at"], t["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_territory(t) for t in page], limit, offset, total)


@bp.route("/sales-planning/territories/<tid>", methods=["GET"])
def get_territory(tid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    t = find_or_404(store.territories, tid, "territory")
    return success_object(calc.ser_territory(t))


@bp.route("/sales-planning/territories/<tid>", methods=["PATCH"])
def patch_territory(tid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    t = find_or_404(store.territories, tid, "territory")
    body = get_body()
    reject_unknown_fields(body, {"name", "potential_cents", "headcount_capacity",
                                 "parent_territory_id"})
    plan = find_or_404(store.plan_years, t["plan_year_id"], "plan year")
    reparenting = "parent_territory_id" in body
    _plan_gate_config_mutation(plan, reparenting=reparenting)

    if "name" in body:
        t["name"] = req_string(body, "name")
    if "potential_cents" in body:
        t["potential_cents"] = req_int(body, "potential_cents", min_value=0)
    if "headcount_capacity" in body:
        t["headcount_capacity"] = req_int(body, "headcount_capacity", min_value=1)
    if reparenting:
        new_parent = body["parent_territory_id"]
        if new_parent is not None:
            if not isinstance(new_parent, str):
                raise ApiError("ERR_INVALID_REQUEST", "parent_territory_id must be a string", 400)
            parent = find_or_404(store.territories, new_parent, "parent territory")
            if parent["plan_year_id"] != plan["id"]:
                raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                               "Parent territory belongs to a different plan year", 409)
            _check_cycle(tid, new_parent)
        t["parent_territory_id"] = new_parent
    touch(t)
    return success_object(calc.ser_territory(t))


@bp.route("/sales-planning/territories/<tid>/activate", methods=["POST"])
def activate_territory(tid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    t = find_or_404(store.territories, tid, "territory")
    plan = find_or_404(store.plan_years, t["plan_year_id"], "plan year")
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("DRAFT", "OPEN"):
        raise ApiError("ERR_PLAN_NOT_OPEN",
                       "Activation requires plan status DRAFT or OPEN", 409)
    if t["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot activate territory in status {t['status']}", 409)
    t["status"] = "ACTIVE"
    touch(t)
    return success_object(calc.ser_territory(t))


@bp.route("/sales-planning/territories/<tid>/deactivate", methods=["POST"])
def deactivate_territory(tid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    t = find_or_404(store.territories, tid, "territory")
    plan = find_or_404(store.plan_years, t["plan_year_id"], "plan year")
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_NOT_OPEN",
                       "Deactivation requires plan status DRAFT", 409)
    if t["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot deactivate territory in status {t['status']}", 409)
    # Guards
    if any(a["plan_year_id"] == plan["id"] and a["assigned_territory_id"] == tid
           for a in store.accounts.values()):
        raise ApiError("ERR_TERRITORY_HAS_ACCOUNTS",
                       "Accounts are still assigned to this territory", 409)
    if any(a["territory_id"] == tid and a["status"] == "ACTIVE"
           for a in store.rep_assignments.values()):
        raise ApiError("ERR_TERRITORY_HAS_ACTIVE_ASSIGNMENTS",
                       "ACTIVE rep assignments exist on this territory", 409)
    t["status"] = "DRAFT"
    touch(t)
    return success_object(calc.ser_territory(t))


@bp.route("/sales-planning/territories/<tid>/retire", methods=["POST"])
def retire_territory(tid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    t = find_or_404(store.territories, tid, "territory")
    plan = find_or_404(store.plan_years, t["plan_year_id"], "plan year")
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("DRAFT", "OPEN"):
        raise ApiError("ERR_PLAN_NOT_OPEN",
                       "Retirement requires plan status DRAFT or OPEN", 409)
    if t["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot retire territory in status {t['status']}", 409)
    if any(a["plan_year_id"] == plan["id"] and a["assigned_territory_id"] == tid
           for a in store.accounts.values()):
        raise ApiError("ERR_TERRITORY_HAS_ACCOUNTS",
                       "Accounts are still assigned to this territory", 409)
    if any(a["territory_id"] == tid and a["status"] == "ACTIVE"
           for a in store.rep_assignments.values()):
        raise ApiError("ERR_TERRITORY_HAS_ACTIVE_ASSIGNMENTS",
                       "ACTIVE rep assignments exist on this territory", 409)
    children = [c for c in store.territories.values()
                if c.get("parent_territory_id") == tid]
    if any(c["status"] != "RETIRED" for c in children):
        raise ApiError("ERR_TERRITORY_HAS_CHILDREN",
                       "Non-RETIRED child territories exist", 409)
    t["status"] = "RETIRED"
    touch(t)
    return success_object(calc.ser_territory(t))
