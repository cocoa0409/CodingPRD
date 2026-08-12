"""Items: cataloguing, patching, declaring value, scheduling and replacement
(PRD 3.3 - 3.5)."""

import calc
import derive
import serializers
import store
from constants import (
    ITEM_CATEGORIES,
    MAX_ITEM_QUANTITY,
    MIN_ITEM_QUANTITY,
    SUBSCRIPTION_TIERS,
)
from errors import ApiError
from registry import endpoint
from routes.common import field, list_response, one

PATCHABLE = ("name", "room_id", "serial_number", "purchase_price_cents", "replacement_cost_cents", "quantity")
NULLABLE_PATCH = ("serial_number", "purchase_price_cents", "replacement_cost_cents")


def item_of(ctx):
    return ctx.row("item_id")


def item_household(ctx):
    return item_of(ctx)["household_id"]


def rung12_item_frozen(ctx):
    if item_of(ctx)["lifecycle_state"] == "FROZEN":
        raise ApiError("ERR_ITEM_FROZEN")


def serial_required_check(category, serial):
    sched = calc.category_schedule_for(category)
    if sched is not None and sched.get("serial_required") and (serial is None or serial == ""):
        raise ApiError("ERR_SERIAL_REQUIRED")


def duplicate_serial_check(household_id, serial, exclude_ids=()):
    if serial is None or serial == "":
        return
    for other in store.items.values():
        if other["id"] in exclude_ids:
            continue
        if (
            other["household_id"] == household_id
            and other.get("serial_number") == serial
            and other["lifecycle_state"] in ("DRAFT", "CATALOGED", "FROZEN")
        ):
            raise ApiError("ERR_DUPLICATE_SERIAL")


def quantity_check(quantity):
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ApiError("ERR_INVALID_QUANTITY")
    if quantity < MIN_ITEM_QUANTITY or quantity > MAX_ITEM_QUANTITY:
        raise ApiError("ERR_INVALID_QUANTITY")


def item_quota_check(household_id):
    sub = derive.subscription_of(household_id)
    if sub is None:
        return
    limits = SUBSCRIPTION_TIERS[sub["tier"]]
    item_usage, _assets, _bytes = calc.quota_usage(household_id)
    if item_usage + 1 > limits["max_items"]:
        raise ApiError("ERR_QUOTA_EXCEEDED")


def new_item_row(household_id, room_id, name, category, acquired_at, quantity, serial_number,
                 purchase_price_cents, replacement_cost_cents, replaces_item_id=None,
                 serial_chain_intact=True):
    row = store.new_row(
        store.items,
        household_id=household_id,
        room_id=room_id,
        name=name,
        category=category,
        quantity=quantity,
        serial_number=serial_number,
        purchase_price_cents=purchase_price_cents,
        replacement_cost_cents=replacement_cost_cents,
        declared_value_cents=0,
        declared_by_member_id=None,
        lifecycle_state="DRAFT",
        evidence_tier="NONE",
        valuation_state="UNVALUED",
        effective_value_cents=0,
        effective_value_basis="NONE",
        acv_value_cents=0,
        coverage_mode="BLANKET",
        scheduled_policy_id=None,
        scheduled_value_cents=0,
        replaces_item_id=replaces_item_id,
        serial_chain_intact=serial_chain_intact,
        allocated_quantity=0,
        frozen_by_claim_id=None,
    )
    derive.keep_raw(row, "acquired_at", acquired_at)
    # PRD 3.3: the new row's acv_value_cents is computed immediately against the
    # current clock, while effective_value_cents stays 0 with basis NONE.
    from timeutil import clock

    row["acv_value_cents"] = calc.acv_cents(row, clock.now)
    return row


def _body_quantity(ctx, default=1):
    if "quantity" in ctx.body and ctx.body["quantity"] is not None:
        return ctx.body["quantity"]
    return default


# ----------------------------------------------------------------- create
def _create_rung22(ctx):
    serial_required_check(ctx.body["category"], ctx.body.get("serial_number"))


def _create_rung23(ctx):
    duplicate_serial_check(ctx.body["household_id"], ctx.body.get("serial_number"))


def _create_rung24(ctx):
    quantity_check(_body_quantity(ctx))


def _create_rung32(ctx):
    item_quota_check(ctx.body["household_id"])


@endpoint(
    "POST",
    "/vault/items",
    roles=["Homeowner", "HouseholdMember"],
    code=201,
    mutating=True,
    body={
        "household_id": ("string", True),
        "room_id": ("string", True),
        "name": ("string", True),
        "category": ("string", True),
        "acquired_at": ("datetime", True),
        "quantity": ("integer", False),
        "serial_number": ("string", False),
        "purchase_price_cents": ("integer", False),
        "replacement_cost_cents": ("integer", False),
    },
    enums={"category": ITEM_CATEGORIES},
    fks=("household_id", "room_id"),
    household=lambda ctx: ctx.body.get("household_id"),
    rungs={22: _create_rung22, 23: _create_rung23, 24: _create_rung24, 32: _create_rung32},
)
def create_item(ctx):
    row = new_item_row(
        ctx.body["household_id"],
        ctx.body["room_id"],
        ctx.body["name"],
        ctx.body["category"],
        ctx.body["acquired_at"],
        _body_quantity(ctx),
        ctx.body.get("serial_number"),
        ctx.body.get("purchase_price_cents"),
        ctx.body.get("replacement_cost_cents"),
    )
    household = store.households.get(row["household_id"])
    room = store.rooms.get(row["room_id"])
    if household is not None:
        derive.recompute_household(household, bump=True)
    if room is not None:
        derive.recompute_room(room, bump=True)
    return one(serializers.item(row, ctx.role), 201)


# ------------------------------------------------------------------- reads
@endpoint(
    "GET",
    "/vault/items/{item_id}",
    roles=[
        "Homeowner",
        "HouseholdMember",
        "EstateExecutor",
        "InsuranceAgent",
        "ClaimsAdjuster",
        "Appraiser",
        "PlatformAdmin",
    ],
    scope_household=item_household,
)
def read_item(ctx):
    return one(serializers.item(item_of(ctx), ctx.role))


@endpoint(
    "GET",
    "/vault/items",
    roles=[
        "Homeowner",
        "HouseholdMember",
        "EstateExecutor",
        "InsuranceAgent",
        "ClaimsAdjuster",
        "Appraiser",
        "PlatformAdmin",
    ],
)
def list_items(ctx):
    return list_response(
        store.all_of(store.items),
        ctx.args,
        lambda row: serializers.item(row, ctx.role),
        {
            "household_id": field("household_id"),
            "room_id": field("room_id"),
            "declared_by_member_id": field("declared_by_member_id"),
            "scheduled_policy_id": field("scheduled_policy_id"),
            "replaces_item_id": field("replaces_item_id"),
            "frozen_by_claim_id": field("frozen_by_claim_id"),
            "evidence_tier": field("evidence_tier"),
            "lifecycle_state": field("lifecycle_state"),
            "valuation_state": field("valuation_state"),
        },
    )


# ------------------------------------------------------------------- patch
def _patch_rung22(ctx):
    item = item_of(ctx)
    serial = ctx.body["serial_number"] if "serial_number" in ctx.body else item.get("serial_number")
    serial_required_check(item["category"], serial)


def _patch_rung23(ctx):
    item = item_of(ctx)
    if "serial_number" not in ctx.body:
        return
    duplicate_serial_check(item["household_id"], ctx.body["serial_number"], exclude_ids=(item["id"],))


def _patch_rung24(ctx):
    if "quantity" in ctx.body and ctx.body["quantity"] is not None:
        quantity_check(ctx.body["quantity"])


@endpoint(
    "PATCH",
    "/vault/items/{item_id}",
    roles=["Homeowner", "HouseholdMember"],
    mutating=True,
    body={
        "name": ("string", False),
        "room_id": ("string", False),
        "serial_number": ("string", False),
        "purchase_price_cents": ("integer", False),
        "replacement_cost_cents": ("integer", False),
        "quantity": ("integer", False),
    },
    fks=("room_id",),
    household=item_household,
    scope_household=item_household,
    rungs={12: rung12_item_frozen, 22: _patch_rung22, 23: _patch_rung23, 24: _patch_rung24},
)
def patch_item(ctx):
    item = item_of(ctx)
    old_room_id = item["room_id"]
    serial_changed = False
    for name in PATCHABLE:
        if name not in ctx.body:
            continue
        value = ctx.body[name]
        if value is None and name not in NULLABLE_PATCH:
            continue
        if name == "serial_number" and value != item.get("serial_number"):
            serial_changed = True
        item[name] = value
    if serial_changed:
        item["evidence_tier"] = calc.evidence_tier_for(item)
    derive.refresh_item(item, bump=False)
    store.touch(item)
    if old_room_id != item["room_id"]:
        for room_id in (old_room_id, item["room_id"]):
            room = store.rooms.get(room_id)
            if room is not None:
                derive.recompute_room(room, bump=False)
    household = store.households.get(item["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=False)
    derive.recompute_policies_for(item["household_id"], bump=False)
    return one(serializers.item(item, ctx.role))


# ---------------------------------------------------------- declare value
@endpoint(
    "POST",
    "/vault/items/{item_id}/declare-value",
    roles=["Homeowner", "HouseholdMember"],
    mutating=True,
    body={"declared_value_cents": ("integer", True)},
    household=item_household,
    scope_household=item_household,
    rungs={12: rung12_item_frozen},
)
def declare_value(ctx):
    item = item_of(ctx)
    item["declared_value_cents"] = ctx.body["declared_value_cents"]
    item["declared_by_member_id"] = ctx.user_id
    derive.refresh_item(item, bump=False)
    derive.maybe_catalog(item)
    store.touch(item)
    household = store.households.get(item["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=False)
    derive.recompute_policies_for(item["household_id"], bump=False)
    return one(serializers.item(item, ctx.role))


# --------------------------------------------------------------- scheduling
def _schedule_rung21(ctx):
    if item_of(ctx)["valuation_state"] == "APPRAISAL_REQUIRED":
        raise ApiError("ERR_APPRAISAL_REQUIRED")


def _schedule_rung36(ctx):
    policy = store.policies[ctx.body["policy_id"]]
    if ctx.body["scheduled_value_cents"] > policy["scheduled_remaining_cents"]:
        raise ApiError("ERR_ALLOWANCE_EXCEEDED")


@endpoint(
    "POST",
    "/vault/items/{item_id}/schedule",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    body={
        "policy_id": ("string", True),
        "scheduled_value_cents": ("integer", True),
        "expected_policy_version": ("integer", True),
    },
    fks=("policy_id",),
    household=item_household,
    scope_household=item_household,
    rungs={12: rung12_item_frozen, 21: _schedule_rung21, 36: _schedule_rung36},
    occ=(
        "expected_policy_version",
        "ERR_STALE_POLICY_VERSION",
        lambda ctx: store.policies.get(ctx.body.get("policy_id")),
    ),
)
def schedule_item(ctx):
    item = item_of(ctx)
    policy = store.policies[ctx.body["policy_id"]]
    amount = ctx.body["scheduled_value_cents"]
    item["coverage_mode"] = "SCHEDULED"
    item["scheduled_policy_id"] = policy["id"]
    item["scheduled_value_cents"] = amount
    policy["scheduled_consumed_cents"] += amount
    store.touch(item)
    derive.recompute_policy(policy, bump=True)
    store.touch(policy)
    household = store.households.get(item["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=False)
    return one(serializers.item(item, ctx.role))


def _unschedule_rung14(ctx):
    if item_of(ctx)["coverage_mode"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")


def release_allowance(item, bump=True):
    """The compensating half of conservation invariant 1: exactly the amount
    this item consumed goes back to the policy."""
    policy = store.policies.get(item.get("scheduled_policy_id"))
    amount = item.get("scheduled_value_cents") or 0
    item["coverage_mode"] = "BLANKET"
    item["scheduled_policy_id"] = None
    item["scheduled_value_cents"] = 0
    if policy is None:
        return None
    policy["scheduled_consumed_cents"] -= amount
    derive.recompute_policy(policy, bump=bump)
    if bump:
        store.touch(policy)
    return policy


@endpoint(
    "POST",
    "/vault/items/{item_id}/unschedule",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    household=item_household,
    scope_household=item_household,
    rungs={12: rung12_item_frozen, 14: _unschedule_rung14},
)
def unschedule_item(ctx):
    item = item_of(ctx)
    release_allowance(item, bump=True)
    store.touch(item)
    household = store.households.get(item["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=False)
    return one(serializers.item(item, ctx.role))


# -------------------------------------------------------------- replacement
def _replace_rung13(ctx):
    if item_of(ctx)["lifecycle_state"] in ("REPLACED", "DISPOSED"):
        raise ApiError("ERR_ALREADY_TERMINAL")


def _replace_rung14(ctx):
    if item_of(ctx)["lifecycle_state"] != "CATALOGED":
        raise ApiError("ERR_INVALID_STATE")


def _replace_rung22(ctx):
    serial_required_check(item_of(ctx)["category"], ctx.body.get("serial_number"))


def _replace_rung23(ctx):
    item = item_of(ctx)
    duplicate_serial_check(item["household_id"], ctx.body.get("serial_number"), exclude_ids=(item["id"],))


def _replace_rung24(ctx):
    quantity_check(_body_quantity(ctx))


def _replace_rung32(ctx):
    item_quota_check(item_of(ctx)["household_id"])


@endpoint(
    "POST",
    "/vault/items/{item_id}/replace",
    roles=["Homeowner"],
    code=201,
    mutating=True,
    owner_only=True,
    body={
        "name": ("string", True),
        "acquired_at": ("datetime", True),
        "serial_number": ("string", False),
        "purchase_price_cents": ("integer", False),
        "replacement_cost_cents": ("integer", False),
        "quantity": ("integer", False),
    },
    household=item_household,
    scope_household=item_household,
    rungs={
        12: rung12_item_frozen,
        13: _replace_rung13,
        14: _replace_rung14,
        22: _replace_rung22,
        23: _replace_rung23,
        24: _replace_rung24,
        32: _replace_rung32,
    },
)
def replace_item(ctx):
    predecessor = item_of(ctx)
    serial = ctx.body.get("serial_number")
    successor = new_item_row(
        predecessor["household_id"],
        predecessor["room_id"],
        ctx.body["name"],
        predecessor["category"],
        ctx.body["acquired_at"],
        _body_quantity(ctx),
        serial,
        ctx.body.get("purchase_price_cents"),
        ctx.body.get("replacement_cost_cents"),
        replaces_item_id=predecessor["id"],
        serial_chain_intact=(serial == predecessor.get("serial_number")),
    )
    predecessor["lifecycle_state"] = "REPLACED"
    if predecessor["coverage_mode"] == "SCHEDULED":
        release_allowance(predecessor, bump=True)
    store.touch(predecessor)
    household = store.households.get(predecessor["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=True)
    derive.recompute_rooms_for(predecessor["household_id"], bump=False)
    derive.recompute_policies_for(predecessor["household_id"], bump=False)
    return one(serializers.item(successor, ctx.role), 201)
