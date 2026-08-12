"""The registry business (PRD 3.9, Pipeline G front half)."""

from flask import Blueprint, g

import constants as C
import serialize
import services
import shapes
import store
from auth import (api, get_registry, get_registry_item, lookup,
                  require_account_owner, require_registry_owner)
from envelope import ok, created, paginate
from errors import ApiError
from routes.children import body_fk
from store import db, touch

bp = Blueprint("registry", __name__)

READ_ROLES = ["RegistryOwner", "GiftPurchaser", "AccountHolder", "SupportAgent",
              "OpsAdmin"]
ITEM_READ_ROLES = ["RegistryOwner", "GiftPurchaser", "SupportAgent", "OpsAdmin"]


@api(bp, "POST", "/registries", ["RegistryOwner", "AccountHolder"])
def create_registry():
    data = shapes.body()
    body_fk(data, "owner_account_id", db.accounts, "Account")
    body_fk(data, "child_id", db.children, "Child")
    parsed = shapes.validate(data, [
        shapes.field("owner_account_id", required=True, kind="string"),
        shapes.field("child_id", required=True, kind="string"),
        shapes.field("title", required=True, kind="string"),
    ])
    require_account_owner(parsed["owner_account_id"])
    require_registry_owner(parsed["owner_account_id"])
    account = db.accounts[parsed["owner_account_id"]]
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")

    row = store.base_row(full=True)
    row.update({
        "owner_account_id": parsed["owner_account_id"],
        "child_id": parsed["child_id"],
        "title": parsed["title"],
        "status": "DRAFT",
        "reopen_count": 0,
        "completion_pct": 0,
        "inflight_gift_count": 0,
    })
    db.registries[row["id"]] = row
    return created(serialize.registry(row))


@api(bp, "GET", "/registries/<id>", READ_ROLES)
def read_registry(id):
    return ok(serialize.registry(get_registry(id)))


@api(bp, "GET", "/registries", READ_ROLES)
def list_registries():
    rows = [r for r in db.registries.values()
            if shapes.match(r, "owner_account_id", shapes.qs("owner_account_id"))
            and shapes.match(r, "child_id", shapes.qs("child_id"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.registry)


@api(bp, "PATCH", "/registries/<id>", ["RegistryOwner"])
def rename_registry(id):
    registry = get_registry(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("title", kind="string"),
    ])
    require_registry_owner(registry["owner_account_id"])
    if shapes.supplied(parsed, "title"):
        registry["title"] = parsed["title"]
    touch(registry)
    return ok(serialize.registry(registry))


@api(bp, "POST", "/registries/<id>/open", ["RegistryOwner"])
def open_registry(id):
    registry = get_registry(id)
    require_registry_owner(registry["owner_account_id"])
    if registry["status"] != "DRAFT":
        raise ApiError("ERR_REGISTRY_STATE_INVALID")
    if not services.items_of_registry(registry["id"]):
        raise ApiError("ERR_REGISTRY_EMPTY")
    registry["status"] = "OPEN"
    touch(registry)
    return ok(serialize.registry(registry))


@api(bp, "POST", "/registries/<id>/close", ["RegistryOwner"])
def close_registry(id):
    registry = get_registry(id)
    require_registry_owner(registry["owner_account_id"])
    if registry["status"] != "OPEN":
        raise ApiError("ERR_REGISTRY_STATE_INVALID")
    registry["status"] = "CLOSED"
    services.recompute_registry(registry)
    touch(registry)
    return ok(serialize.registry(registry))


@api(bp, "POST", "/registries/<id>/reopen", ["RegistryOwner"])
def reopen_registry(id):
    registry = get_registry(id)
    require_registry_owner(registry["owner_account_id"])
    if registry["status"] != "CLOSED":
        raise ApiError("ERR_REGISTRY_STATE_INVALID")
    if int(registry["reopen_count"]) >= C.REGISTRY_REOPEN_CAP:
        raise ApiError("ERR_REGISTRY_REOPEN_CAP")
    registry["status"] = "OPEN"
    registry["reopen_count"] = int(registry["reopen_count"]) + 1
    touch(registry)
    return ok(serialize.registry(registry))


@api(bp, "POST", "/registries/<id>/archive", ["RegistryOwner"])
def archive_registry(id):
    registry = get_registry(id)
    require_registry_owner(registry["owner_account_id"])
    if registry["status"] != "CLOSED":
        raise ApiError("ERR_REGISTRY_STATE_INVALID")
    services.recompute_registry(registry)
    if int(registry["inflight_gift_count"]) != 0:
        raise ApiError("ERR_REGISTRY_HAS_INFLIGHT_GIFTS")
    registry["status"] = "ARCHIVED"
    touch(registry)
    return ok(serialize.registry(registry))


@api(bp, "GET", "/registries/<id>/summary", ITEM_READ_ROLES)
def registry_summary(id):
    registry = get_registry(id)
    services.recompute_registry(registry)
    items = services.items_of_registry(registry["id"])
    return ok({
        "item_count": len(items),
        "requested_units": sum(int(i["requested_quantity"]) for i in items),
        "fulfilled_units": sum(int(i["fulfilled_quantity"]) for i in items),
        "completion_pct": registry["completion_pct"],
        "inflight_gift_count": registry["inflight_gift_count"],
    })


@api(bp, "POST", "/registries/<id>/items", ["RegistryOwner"])
def add_item(id):
    registry = get_registry(id)
    data = shapes.body()
    body_fk(data, "sku_id", db.skus, "Sku")
    parsed = shapes.validate(data, [
        shapes.field("sku_id", required=True, kind="string"),
        shapes.field("requested_quantity", required=True, kind="int", lo=1,
                     hi=C.REGISTRY_ITEM_QTY_MAX),
    ])
    require_registry_owner(registry["owner_account_id"])
    sku = db.skus[parsed["sku_id"]]
    if sku["status"] != "ACTIVE":
        raise ApiError("ERR_SKU_DISCONTINUED")

    row = store.base_row(full=True)
    row.update({
        "registry_id": registry["id"],
        "sku_id": parsed["sku_id"],
        "requested_quantity": parsed["requested_quantity"],
        "fulfilled_quantity": 0,
        "status": "REQUESTED",
    })
    db.registry_items[row["id"]] = row
    services.recompute_registry(registry)
    touch(registry)
    return created(serialize.registry_item(row))


@api(bp, "GET", "/registry-items/<id>", ITEM_READ_ROLES)
def read_item(id):
    return ok(serialize.registry_item(get_registry_item(id)))


@api(bp, "GET", "/registry-items", ITEM_READ_ROLES)
def list_items():
    rows = [r for r in db.registry_items.values()
            if shapes.match(r, "registry_id", shapes.qs("registry_id"))
            and shapes.match(r, "sku_id", shapes.qs("sku_id"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.registry_item)


@api(bp, "PATCH", "/registries/<id>/items/<item_id>", ["RegistryOwner"])
def update_item(id, item_id):
    registry = get_registry(id)
    item = get_registry_item(item_id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("requested_quantity", kind="int", lo=1,
                     hi=C.REGISTRY_ITEM_QTY_MAX),
    ])
    require_registry_owner(registry["owner_account_id"])
    if item["registry_id"] != registry["id"]:
        raise ApiError("ERR_REGISTRY_ITEM_MISMATCH")
    if shapes.supplied(parsed, "requested_quantity"):
        item["requested_quantity"] = parsed["requested_quantity"]
    touch(item)
    services.recompute_registry(registry)
    touch(registry)
    return ok(serialize.registry_item(item))


@api(bp, "DELETE", "/registries/<id>/items/<item_id>", ["RegistryOwner"])
def delete_item(id, item_id):
    registry = get_registry(id)
    item = get_registry_item(item_id)
    require_registry_owner(registry["owner_account_id"])
    for gift in services.gifts_of_item(item["id"]):
        if gift["status"] != "REFUNDED":
            raise ApiError("ERR_REGISTRY_ITEM_HAS_GIFTS")
    if item["registry_id"] != registry["id"]:
        raise ApiError("ERR_REGISTRY_ITEM_MISMATCH")
    payload = serialize.registry_item(item)
    db.registry_items.pop(item["id"], None)
    services.recompute_registry(registry)
    touch(registry)
    return ok(payload)
