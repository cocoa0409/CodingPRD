"""Estate and downsizing dispositions (PRD 3.8)."""

import calc
import derive
import serializers
import store
from constants import DISPOSITIONS, LIVE_PLAN_STATES, VALUATION_MODES
from errors import ApiError
from registry import endpoint
from routes.common import field, list_response, one
from routes.items import release_allowance
from timeutil import clock


def _plan(ctx):
    return ctx.row("estate_plan_id")


def _plan_household(ctx):
    return _plan(ctx)["household_id"]


def _allocation(ctx):
    return ctx.row("allocation_id")


def _allocation_plan(ctx):
    return store.estate_plans.get(_allocation(ctx)["estate_plan_id"])


def _allocation_household(ctx):
    plan = _allocation_plan(ctx)
    return plan["household_id"] if plan else None


# ------------------------------------------------------------------- plans
def _plan_create_rung14(ctx):
    if derive.live_plan_of(ctx.body["household_id"]) is not None:
        raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/estate-plans",
    roles=["Homeowner"],
    code=201,
    mutating=True,
    owner_only=True,
    body={
        "household_id": ("string", True),
        "executor_member_id": ("string", True),
        "valuation_mode": ("string", False),
    },
    enums={"valuation_mode": VALUATION_MODES},
    fks=("household_id", "executor_member_id"),
    household=lambda ctx: ctx.body.get("household_id"),
    rungs={14: _plan_create_rung14},
)
def create_estate_plan(ctx):
    row = store.new_row(
        store.estate_plans,
        household_id=ctx.body["household_id"],
        executor_member_id=ctx.body["executor_member_id"],
        status="DRAFT",
        valuation_mode=ctx.body.get("valuation_mode") or "GROSS",
        approved_by_member_id=None,
        heir_count=0,
        balance_spread_pct=None,
        balanced=False,
        unallocated_item_count=0,
    )
    derive.stamp(row, "proposed_at", None)
    derive.stamp(row, "approved_at", None)
    derive.stamp(row, "executed_at", None)
    derive.recompute_plan(row, bump=False)
    return one(serializers.estate_plan(row), 201)


@endpoint(
    "GET",
    "/vault/estate-plans/{estate_plan_id}",
    roles=["Homeowner", "EstateExecutor", "PlatformAdmin"],
    scope_household=_plan_household,
)
def read_estate_plan(ctx):
    plan = _plan(ctx)
    derive.recompute_plan(plan, bump=False)
    return one(serializers.estate_plan(plan))


@endpoint("GET", "/vault/estate-plans", roles=["Homeowner", "EstateExecutor", "PlatformAdmin"])
def list_estate_plans(ctx):
    rows = store.all_of(store.estate_plans)
    for plan in rows:
        derive.recompute_plan(plan, bump=False)
    return list_response(
        rows,
        ctx.args,
        serializers.estate_plan,
        {
            "household_id": field("household_id"),
            "executor_member_id": field("executor_member_id"),
            "approved_by_member_id": field("approved_by_member_id"),
            "status": field("status"),
        },
    )


# ------------------------------------------------------------- allocations
def _heir_pairing(ctx):
    disposition = ctx.body.get("disposition")
    if disposition not in DISPOSITIONS:
        return
    heir = ctx.body.get("heir_member_id")
    if disposition == "KEEP" and heir is None:
        raise ApiError("ERR_INVALID_REQUEST", "heir_member_id is required for a KEEP allocation.")
    if disposition != "KEEP" and heir is not None:
        raise ApiError("ERR_INVALID_REQUEST", "heir_member_id must be null for this disposition.")


def _alloc_rung24(ctx):
    quantity = ctx.body["quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        raise ApiError("ERR_INVALID_QUANTITY")


def _alloc_rung25(ctx):
    item = store.items[ctx.body["item_id"]]
    if item["allocated_quantity"] + ctx.body["quantity"] > item["quantity"]:
        raise ApiError("ERR_ALLOCATION_OVER_QUANTITY")


def _alloc_rung26(ctx):
    item = store.items[ctx.body["item_id"]]
    if item["lifecycle_state"] == "FROZEN":
        raise ApiError("ERR_ITEM_NOT_DISPOSABLE")
    for appraisal in store.appraisals.values():
        if appraisal["item_id"] == item["id"] and appraisal["status"] == "REQUESTED":
            raise ApiError("ERR_ITEM_NOT_DISPOSABLE")


@endpoint(
    "POST",
    "/vault/estate-plans/{estate_plan_id}/allocations",
    roles=["EstateExecutor"],
    code=201,
    mutating=True,
    executor_only=True,
    body={
        "item_id": ("string", True),
        "disposition": ("string", True),
        "quantity": ("integer", True),
        "expected_estate_plan_version": ("integer", True),
        "heir_member_id": ("string", False),
    },
    enums={"disposition": DISPOSITIONS},
    fks=("item_id", "heir_member_id"),
    household=_plan_household,
    scope_household=_plan_household,
    plan_target=_plan,
    rung3_extra=_heir_pairing,
    rungs={24: _alloc_rung24, 25: _alloc_rung25, 26: _alloc_rung26},
    occ=("expected_estate_plan_version", "ERR_STALE_PLAN_VERSION", _plan),
)
def create_allocation(ctx):
    plan = _plan(ctx)
    item = store.items[ctx.body["item_id"]]
    row = store.new_row(
        store.allocations,
        estate_plan_id=plan["id"],
        item_id=item["id"],
        heir_member_id=ctx.body.get("heir_member_id"),
        disposition=ctx.body["disposition"],
        quantity=ctx.body["quantity"],
        allocated_value_cents=calc.allocation_value(item, ctx.body["quantity"]),
        blocked=False,
    )
    derive.recompute_item_allocation(item, bump=False)
    store.touch(item)
    derive.recompute_plan(plan, bump=False)
    store.touch(plan)
    return one(serializers.allocation(row), 201)


@endpoint(
    "GET",
    "/vault/allocations/{allocation_id}",
    roles=["Homeowner", "EstateExecutor", "PlatformAdmin"],
    scope_household=_allocation_household,
)
def read_allocation(ctx):
    return one(serializers.allocation(_allocation(ctx)))


@endpoint("GET", "/vault/allocations", roles=["Homeowner", "EstateExecutor", "PlatformAdmin"])
def list_allocations(ctx):
    return list_response(
        store.all_of(store.allocations),
        ctx.args,
        serializers.allocation,
        {
            "estate_plan_id": field("estate_plan_id"),
            "item_id": field("item_id"),
            "heir_member_id": field("heir_member_id"),
            "disposition": field("disposition"),
        },
    )


@endpoint(
    "DELETE",
    "/vault/allocations/{allocation_id}",
    roles=["EstateExecutor"],
    mutating=True,
    executor_only=True,
    household=_allocation_household,
    scope_household=_allocation_household,
    plan_target=_allocation_plan,
)
def delete_allocation(ctx):
    allocation = _allocation(ctx)
    plan = _allocation_plan(ctx)
    item = store.items.get(allocation["item_id"])
    payload = serializers.allocation(allocation)
    store.allocations.pop(allocation["id"], None)
    if item is not None:
        derive.recompute_item_allocation(item, bump=False)
        store.touch(item)
    if plan is not None:
        if plan["status"] == "PROPOSED":
            plan["status"] = "DRAFT"
            plan["balance_spread_pct"] = None
            plan["balanced"] = False
        derive.recompute_plan(plan, bump=False)
        store.touch(plan)
    return one(payload)


# ------------------------------------------------------------------ propose
def _propose_rung13(ctx):
    if _plan(ctx)["status"] == "EXECUTED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _propose_rung14(ctx):
    plan = _plan(ctx)
    if plan["status"] not in ("DRAFT", "PROPOSED"):
        raise ApiError("ERR_INVALID_STATE")
    for allocation in derive.plan_allocations(plan["id"]):
        if allocation["blocked"]:
            raise ApiError("ERR_INVALID_STATE")


def _propose_rung27(ctx):
    plan = _plan(ctx)
    derive.recompute_plan(plan, bump=False)
    if plan["unallocated_item_count"] > 0:
        raise ApiError("ERR_PLAN_NOT_FULLY_ALLOCATED")


@endpoint(
    "POST",
    "/vault/estate-plans/{estate_plan_id}/propose",
    roles=["EstateExecutor"],
    mutating=True,
    executor_only=True,
    body={"valuation_mode": ("string", False)},
    enums={"valuation_mode": VALUATION_MODES},
    household=_plan_household,
    scope_household=_plan_household,
    plan_target=_plan,
    rungs={13: _propose_rung13, 14: _propose_rung14, 27: _propose_rung27},
)
def propose_plan(ctx):
    plan = _plan(ctx)
    if ctx.body.get("valuation_mode") is not None:
        plan["valuation_mode"] = ctx.body["valuation_mode"]
    heir_count, spread, balanced = calc.fair_division(
        plan, derive.plan_allocations(plan["id"]), plan["valuation_mode"]
    )
    plan["heir_count"] = heir_count
    plan["balance_spread_pct"] = spread
    plan["balanced"] = balanced
    plan["status"] = "PROPOSED"
    derive.stamp(plan, "proposed_at", clock.now)
    store.touch(plan)
    return one(serializers.estate_plan(plan))


# ------------------------------------------------------------------ approve
def _approve_rung13(ctx):
    if _plan(ctx)["status"] == "EXECUTED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _approve_rung14(ctx):
    if _plan(ctx)["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE")


def _approve_rung16(ctx):
    if ctx.user_id == _plan(ctx)["executor_member_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")


def _approve_rung28(ctx):
    plan = _plan(ctx)
    if not plan["balanced"] and ctx.body.get("override_unbalanced") is not True:
        raise ApiError("ERR_PLAN_UNBALANCED")


@endpoint(
    "POST",
    "/vault/estate-plans/{estate_plan_id}/approve",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    body={"override_unbalanced": ("boolean", False)},
    household=_plan_household,
    scope_household=_plan_household,
    rungs={13: _approve_rung13, 14: _approve_rung14, 16: _approve_rung16, 28: _approve_rung28},
)
def approve_plan(ctx):
    plan = _plan(ctx)
    plan["status"] = "APPROVED"
    derive.stamp(plan, "approved_at", clock.now)
    plan["approved_by_member_id"] = ctx.user_id
    store.touch(plan)
    return one(serializers.estate_plan(plan))


# ------------------------------------------------------------------ execute
def _execute_rung13(ctx):
    if _plan(ctx)["status"] == "EXECUTED":
        raise ApiError("ERR_ALREADY_TERMINAL")


def _execute_rung14(ctx):
    plan = _plan(ctx)
    if plan["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    for allocation in derive.plan_allocations(plan["id"]):
        if allocation["blocked"]:
            raise ApiError("ERR_INVALID_STATE")


@endpoint(
    "POST",
    "/vault/estate-plans/{estate_plan_id}/execute",
    roles=["EstateExecutor"],
    mutating=True,
    executor_only=True,
    household=_plan_household,
    scope_household=_plan_household,
    plan_target=_plan,
    rungs={13: _execute_rung13, 14: _execute_rung14},
)
def execute_plan(ctx):
    plan = _plan(ctx)
    plan["status"] = "EXECUTED"
    derive.stamp(plan, "executed_at", clock.now)
    store.touch(plan)

    disposed_by_item = {}
    for allocation in derive.plan_allocations(plan["id"]):
        if allocation["disposition"] in ("SELL", "DONATE", "DISCARD"):
            disposed_by_item[allocation["item_id"]] = (
                disposed_by_item.get(allocation["item_id"], 0) + allocation["quantity"]
            )
    for item_id, quantity in disposed_by_item.items():
        item = store.items.get(item_id)
        if item is None or item["lifecycle_state"] != "CATALOGED":
            continue
        if quantity != item["quantity"]:
            continue
        item["lifecycle_state"] = "DISPOSED"
        if item["coverage_mode"] == "SCHEDULED":
            release_allowance(item, bump=True)
        store.touch(item)
    # An EXECUTED plan drops out of the allocated_quantity sum entirely.
    for allocation in derive.plan_allocations(plan["id"]):
        allocated_item = store.items.get(allocation["item_id"])
        if allocated_item is not None:
            derive.recompute_item_allocation(allocated_item, bump=False)
    household = store.households.get(plan["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=True)
        store.touch(household)
    derive.recompute_rooms_for(plan["household_id"], bump=False)
    derive.recompute_policies_for(plan["household_id"], bump=False)
    return one(serializers.estate_plan(plan))
