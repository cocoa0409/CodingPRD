"""Evidence assets and the evidence tier (PRD 3.3)."""

import calc
import cascades
import derive
import serializers
import store
from constants import ASSET_KINDS, CLAIM_MIN_EVIDENCE_TIER_RANK, EVIDENCE_RANK, SUBSCRIPTION_TIERS
from errors import ApiError
from registry import endpoint
from routes.common import field, list_response, one
from routes.items import item_household, item_of, rung12_item_frozen


def _asset(ctx):
    return ctx.row("asset_id")


def _asset_item(ctx):
    return store.items.get(_asset(ctx)["item_id"])


def _asset_household(ctx):
    item = _asset_item(ctx)
    return item["household_id"] if item else None


def _asset_rung12(ctx):
    item = _asset_item(ctx)
    if item is not None and item["lifecycle_state"] == "FROZEN":
        raise ApiError("ERR_ITEM_FROZEN")


def _byte_size_check(ctx):
    size = ctx.body.get("byte_size")
    if isinstance(size, int) and not isinstance(size, bool) and size < 1:
        raise ApiError("ERR_INVALID_REQUEST", "byte_size must be at least 1.")


def _upload_rung32(ctx):
    item = item_of(ctx)
    sub = derive.subscription_of(item["household_id"])
    if sub is None:
        return
    limits = SUBSCRIPTION_TIERS[sub["tier"]]
    _items, asset_usage, bytes_usage = calc.quota_usage(item["household_id"])
    if asset_usage + 1 > limits["max_assets"]:
        raise ApiError("ERR_QUOTA_EXCEEDED")
    if bytes_usage + ctx.body["byte_size"] > limits["max_asset_bytes"]:
        raise ApiError("ERR_QUOTA_EXCEEDED")


@endpoint(
    "POST",
    "/vault/items/{item_id}/assets",
    roles=["Homeowner", "HouseholdMember"],
    code=201,
    mutating=True,
    body={
        "asset_kind": ("string", True),
        "byte_size": ("integer", True),
        "checksum": ("string", True),
        "captured_at": ("datetime", True),
    },
    enums={"asset_kind": ASSET_KINDS},
    household=item_household,
    scope_household=item_household,
    rung3_extra=_byte_size_check,
    rungs={12: rung12_item_frozen, 32: _upload_rung32},
)
def upload_asset(ctx):
    item = item_of(ctx)
    row = store.new_row(
        store.assets,
        common_fields=False,
        item_id=item["id"],
        asset_kind=ctx.body["asset_kind"],
        byte_size=ctx.body["byte_size"],
        checksum=ctx.body["checksum"],
        status="STORED",
    )
    derive.keep_raw(row, "captured_at", ctx.body["captured_at"])
    item["evidence_tier"] = calc.evidence_tier_for(item)
    derive.refresh_item(item, bump=False)
    derive.maybe_catalog(item)
    store.touch(item)
    household = store.households.get(item["household_id"])
    if household is not None:
        derive.recompute_household(household, bump=True)
    derive.recompute_policies_for(item["household_id"], bump=False)
    return one(serializers.asset(row), 201)


@endpoint(
    "GET",
    "/vault/assets/{asset_id}",
    roles=["Homeowner", "HouseholdMember", "Appraiser", "ClaimsAdjuster", "PlatformAdmin"],
    scope_household=_asset_household,
)
def read_asset(ctx):
    return one(serializers.asset(_asset(ctx)))


@endpoint(
    "GET",
    "/vault/assets",
    roles=["Homeowner", "HouseholdMember", "Appraiser", "ClaimsAdjuster", "PlatformAdmin"],
)
def list_assets(ctx):
    return list_response(
        store.all_of(store.assets),
        ctx.args,
        serializers.asset,
        {
            "item_id": field("item_id"),
            "status": field("status"),
            "asset_kind": field("asset_kind"),
        },
    )


@endpoint(
    "DELETE",
    "/vault/assets/{asset_id}",
    roles=["Homeowner"],
    mutating=True,
    owner_only=True,
    household=_asset_household,
    scope_household=_asset_household,
    rungs={12: _asset_rung12},
)
def delete_asset(ctx):
    asset = _asset(ctx)
    item = _asset_item(ctx)
    asset["status"] = "DELETED"
    if item is not None:
        item["evidence_tier"] = calc.evidence_tier_for(item)
        derive.refresh_item(item, bump=False)
        store.touch(item)
        if EVIDENCE_RANK[item["evidence_tier"]] < CLAIM_MIN_EVIDENCE_TIER_RANK:
            cascades.evidence_downgrade_cascade(item)
        household = store.households.get(item["household_id"])
        if household is not None:
            derive.recompute_household(household, bump=True)
        derive.recompute_policies_for(item["household_id"], bump=False)
    return one(serializers.asset(asset))
