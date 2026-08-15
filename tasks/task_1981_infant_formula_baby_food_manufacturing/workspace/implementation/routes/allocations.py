"""AllocationPlan and AllocationEntry endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import store, now, new_id
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_INVALID_RANGE, ERR_STALE_VERSION,
                    ERR_ALLOCATION_PLAN_EMPTY, ERR_FULFILLMENT_EXCEEDS_ALLOCATION)
from middleware import authorized
from response import ok, paginate
from services import (ser_plan, ser_entry, get_or_404, stamp_new, touch,
                      run_allocation, check_plan_fulfillment, ALLOCATION_METHODS)
from util import get_body, require_fields, check_enum, to_decimal

bp = Blueprint("allocations", __name__)

PLAN_READ = ("SUPPLY_CHAIN_PLANNER", "QA_MANAGER")


def _plan_entries(plan_id):
    return [e for e in store.entries.values() if e["plan_id"] == plan_id]


# ------------------------------------------------------------------ plans
@bp.post("/allocation-plans")
@authorized("SUPPLY_CHAIN_PLANNER")
def create_plan(_user_id=None, _role=None):
    body = get_body()
    formula = None
    if body.get("formula_id") is not None:
        formula = get_or_404(store.formulas, body["formula_id"], "Formula")
    require_fields(body, ["formula_id", "total_available_kg", "allocation_method"])
    method = check_enum(body["allocation_method"], ALLOCATION_METHODS, "allocation_method")
    total = to_decimal(body["total_available_kg"], "total_available_kg")
    if total <= 0:
        raise err(ERR_INVALID_RANGE, "total_available_kg must be greater than 0")
    rec = stamp_new({
        "id": new_id(),
        "plan_ref": store.next_ref("A"),
        "formula_id": formula["id"],
        "total_available_kg": total.quantize(Decimal("0.001")),
        "allocation_method": method,
        "status": "DRAFT",
        "activated_at": None,
        "fulfilled_at": None,
    })
    store.plans[rec["id"]] = rec
    return ok(ser_plan(rec), 201)


@bp.get("/allocation-plans")
@authorized(*PLAN_READ)
def list_plans(_user_id=None, _role=None):
    records = list(store.plans.values())
    for param, field in (("status", "status"), ("formula_id", "formula_id")):
        v = request.args.get(param)
        if v is not None:
            records = [p for p in records if p[field] == v]
    return paginate(records, ser_plan)


@bp.get("/allocation-plans/<pid>")
@authorized(*PLAN_READ)
def get_plan(pid, _user_id=None, _role=None):
    return ok(ser_plan(get_or_404(store.plans, pid, "AllocationPlan")))


@bp.post("/allocation-plans/<pid>/activate")
@authorized("SUPPLY_CHAIN_PLANNER")
def activate_plan(pid, _user_id=None, _role=None):
    plan = get_or_404(store.plans, pid, "AllocationPlan")
    if plan["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  "AllocationPlan in status %s cannot be activated" % plan["status"])
    entries = _plan_entries(plan["id"])
    if not entries:
        raise err(ERR_ALLOCATION_PLAN_EMPTY,
                  "Allocation plan must have at least one entry before activation")
    if plan["total_available_kg"] <= 0:
        raise err(ERR_INVALID_RANGE, "total_available_kg must be greater than 0")
    body = get_body()
    require_fields(body, ["expected_plan_version"])
    expected = body["expected_plan_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, "expected_plan_version must be an integer")
    if expected != plan["version"]:
        raise err(ERR_STALE_VERSION,
                  "expected_plan_version %s does not match current plan version %s"
                  % (expected, plan["version"]))
    run_allocation(plan, entries)
    for e in entries:
        touch(e)
    plan["status"] = "ACTIVE"
    plan["activated_at"] = now()
    touch(plan)
    return ok(ser_plan(plan), 201)


@bp.post("/allocation-plans/<pid>/cancel")
@authorized("SUPPLY_CHAIN_PLANNER")
def cancel_plan(pid, _user_id=None, _role=None):
    plan = get_or_404(store.plans, pid, "AllocationPlan")
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise err(ERR_INVALID_STATE,
                  "AllocationPlan in status %s cannot be cancelled" % plan["status"])
    if plan["status"] == "ACTIVE":
        if any(e["fulfilled_kg"] > 0 for e in _plan_entries(plan["id"])):
            raise err(ERR_INVALID_STATE,
                      "Cannot cancel an ACTIVE plan with recorded fulfillments")
    plan["status"] = "CANCELLED"
    touch(plan)
    return ok(ser_plan(plan))


# ------------------------------------------------------------------ entries
@bp.post("/allocation-plans/<pid>/entries")
@authorized("SUPPLY_CHAIN_PLANNER")
def create_entry(pid, _user_id=None, _role=None):
    plan = get_or_404(store.plans, pid, "AllocationPlan")
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise err(ERR_INVALID_STATE,
                  "AllocationPlan in status %s cannot accept entries" % plan["status"])
    body = get_body()
    require_fields(body, ["customer_code", "customer_name", "requested_kg"])
    requested = to_decimal(body["requested_kg"], "requested_kg")
    if requested <= 0:
        raise err(ERR_INVALID_RANGE, "requested_kg must be greater than 0")
    tier = body.get("priority_tier")
    if tier is not None:
        if isinstance(tier, bool) or not isinstance(tier, int) or tier < 1 or tier > 10:
            raise err(ERR_INVALID_RANGE,
                      "priority_tier must be an integer between 1 and 10")
    rec = stamp_new({
        "id": new_id(),
        "plan_id": plan["id"],
        "customer_code": body["customer_code"],
        "customer_name": body["customer_name"],
        "requested_kg": requested.quantize(Decimal("0.001")),
        "priority_tier": tier,
        "allocated_kg": Decimal("0"),
        "fulfilled_kg": Decimal("0"),
        "status": "PENDING",
    })
    store.entries[rec["id"]] = rec
    # entry mutation cascades onto the plan version
    touch(plan)
    # provisional -> final recompute: rerun when activated but not yet fulfilled
    if plan["status"] == "ACTIVE":
        entries = _plan_entries(plan["id"])
        if not any(e["fulfilled_kg"] > 0 for e in entries):
            run_allocation(plan, entries)
            for e in entries:
                if e["id"] != rec["id"]:
                    touch(e)
    return ok(ser_entry(rec), 201)


@bp.get("/allocation-plans/<pid>/entries")
@authorized(*PLAN_READ)
def list_plan_entries(pid, _user_id=None, _role=None):
    get_or_404(store.plans, pid, "AllocationPlan")
    records = _plan_entries(pid)
    status = request.args.get("status")
    if status is not None:
        records = [e for e in records if e["status"] == status]
    return paginate(records, ser_entry)


@bp.get("/allocation-entries/<eid>")
@authorized(*PLAN_READ)
def get_entry(eid, _user_id=None, _role=None):
    return ok(ser_entry(get_or_404(store.entries, eid, "AllocationEntry")))


@bp.post("/allocation-entries/<eid>/record-fulfillment")
@authorized("SUPPLY_CHAIN_PLANNER")
def record_fulfillment(eid, _user_id=None, _role=None):
    entry = get_or_404(store.entries, eid, "AllocationEntry")
    plan = store.plans.get(entry["plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE,
                  "Parent AllocationPlan is not ACTIVE")
    if entry["status"] not in ("PENDING", "PARTIALLY_FULFILLED"):
        raise err(ERR_INVALID_STATE,
                  "AllocationEntry in status %s cannot record fulfillment" % entry["status"])
    body = get_body()
    require_fields(body, ["fulfilled_kg"])
    amount = to_decimal(body["fulfilled_kg"], "fulfilled_kg")
    if amount <= 0:
        raise err(ERR_INVALID_RANGE, "fulfilled_kg must be greater than 0")
    amount = amount.quantize(Decimal("0.001"))
    new_total = entry["fulfilled_kg"] + amount
    if new_total > entry["allocated_kg"]:
        raise err(ERR_FULFILLMENT_EXCEEDS_ALLOCATION,
                  "Cumulative fulfilled_kg would exceed allocated_kg")
    entry["fulfilled_kg"] = new_total
    if new_total == entry["allocated_kg"]:
        entry["status"] = "FULFILLED"
    else:
        entry["status"] = "PARTIALLY_FULFILLED"
    touch(entry)
    check_plan_fulfillment(plan)
    return ok(ser_entry(entry))


@bp.post("/allocation-entries/<eid>/mark-shortfall")
@authorized("SUPPLY_CHAIN_PLANNER")
def mark_shortfall(eid, _user_id=None, _role=None):
    entry = get_or_404(store.entries, eid, "AllocationEntry")
    plan = store.plans.get(entry["plan_id"])
    if plan is None or plan["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE,
                  "Parent AllocationPlan is not ACTIVE")
    if entry["status"] == "PENDING":
        if not entry["allocated_kg"] < entry["requested_kg"]:
            raise err(ERR_INVALID_STATE,
                      "Shortfall from PENDING requires allocated_kg < requested_kg")
    elif entry["status"] == "PARTIALLY_FULFILLED":
        if not entry["fulfilled_kg"] < entry["allocated_kg"]:
            raise err(ERR_INVALID_STATE,
                      "Shortfall from PARTIALLY_FULFILLED requires fulfilled_kg < allocated_kg")
    else:
        raise err(ERR_INVALID_STATE,
                  "AllocationEntry in status %s cannot be marked shortfall" % entry["status"])
    body = get_body()
    require_fields(body, ["shortfall_reason"])
    entry["status"] = "SHORTFALL"
    touch(entry)
    check_plan_fulfillment(plan)
    return ok(ser_entry(entry))
