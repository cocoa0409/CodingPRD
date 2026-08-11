"""Gift orders: reserve, pay, claim, refund (PRD 3.9, Pipeline G back half)."""

from flask import Blueprint, g

import calc
import constants as C
import serialize
import services
import shapes
import store
from auth import (api, get_gift_order, lookup, require_gift_purchaser,
                  require_registry_owner)
from envelope import ok, created, paginate
from errors import ApiError
from routes.children import body_fk
from store import db, now, touch

bp = Blueprint("gifts", __name__)

READ_ROLES = ["GiftPurchaser", "RegistryOwner", "SupportAgent", "OpsAdmin"]


def _item_of(gift):
    return db.registry_items.get(gift["registry_item_id"])


def _registry_of(gift):
    item = _item_of(gift)
    return services.registry_of_item(item) if item else None


@api(bp, "POST", "/gift-orders", ["GiftPurchaser"])
def create_gift():
    data = shapes.body()
    body_fk(data, "registry_item_id", db.registry_items, "RegistryItem")
    body_fk(data, "purchaser_account_id", db.accounts, "Account")
    parsed = shapes.validate(data, [
        shapes.field("registry_item_id", required=True, kind="string"),
        shapes.field("purchaser_account_id", required=True, kind="string"),
        shapes.field("quantity", required=True, kind="int", lo=1),
        shapes.field("expected_registry_item_version", required=True, kind="int"),
        shapes.field("gift_message", kind="string", default=None),
    ])
    require_gift_purchaser(parsed["purchaser_account_id"])

    item = db.registry_items[parsed["registry_item_id"]]
    # G6 — optimistic concurrency on the parent RegistryItem's version.
    if parsed["expected_registry_item_version"] != int(item["version"]):
        raise ApiError("ERR_STALE_REGISTRY_ITEM_VERSION")

    account = db.accounts[parsed["purchaser_account_id"]]
    registry = services.registry_of_item(item)
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE")
    if registry is None or registry["status"] != "OPEN":
        raise ApiError("ERR_REGISTRY_CLOSED")
    if item["status"] == "FULFILLED":
        raise ApiError("ERR_REGISTRY_ITEM_FULFILLED")
    remaining = int(item["requested_quantity"]) - int(item["fulfilled_quantity"])
    if parsed["quantity"] > remaining:
        raise ApiError("ERR_GIFT_QUANTITY_EXCEEDS_REMAINING")
    if parsed["purchaser_account_id"] == registry["owner_account_id"]:
        raise ApiError("ERR_SELF_GIFT_FORBIDDEN")

    row = store.base_row(full=True)
    row.update({
        "registry_item_id": item["id"],
        "purchaser_account_id": parsed["purchaser_account_id"],
        "quantity": parsed["quantity"],
        "gift_message": parsed["gift_message"],
        "paid_cents": 0,
        "claim_mode": None,
        "status": "PENDING_PAYMENT",
        "paid_at": None,
        "claimed_at": None,
    })
    db.gift_orders[row["id"]] = row
    touch(item)
    return created(serialize.gift_order(row))


@api(bp, "GET", "/gift-orders/<id>", READ_ROLES)
def read_gift(id):
    return ok(serialize.gift_order(get_gift_order(id)))


@api(bp, "GET", "/gift-orders", READ_ROLES)
def list_gifts():
    rows = [r for r in db.gift_orders.values()
            if shapes.match(r, "registry_item_id", shapes.qs("registry_item_id"))
            and shapes.match(r, "purchaser_account_id",
                             shapes.qs("purchaser_account_id"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.gift_order)


@api(bp, "POST", "/gift-orders/<id>/pay", ["GiftPurchaser"])
def pay_gift(id):
    gift = get_gift_order(id)
    require_gift_purchaser(gift["purchaser_account_id"])
    item = _item_of(gift)
    registry = _registry_of(gift)
    if registry is None or registry["status"] != "OPEN":
        raise ApiError("ERR_REGISTRY_CLOSED")
    if item["status"] == "FULFILLED":
        raise ApiError("ERR_REGISTRY_ITEM_FULFILLED")
    if gift["status"] != "PENDING_PAYMENT":
        raise ApiError("ERR_GIFT_ORDER_STATE_INVALID")
    remaining = int(item["requested_quantity"]) - int(item["fulfilled_quantity"])
    if int(gift["quantity"]) > remaining:
        raise ApiError("ERR_GIFT_QUANTITY_EXCEEDS_REMAINING")

    sku = db.skus.get(item["sku_id"])
    unit = calc.effective_unit_price(sku) if sku else 0
    gift["paid_cents"] = int(gift["quantity"]) * unit
    gift["paid_at"] = now()
    gift["status"] = "PAID"
    touch(gift)
    services.apply_item_fulfilment(item, int(gift["quantity"]))
    return ok(serialize.gift_order(gift))


@api(bp, "POST", "/gift-orders/<id>/claim", ["RegistryOwner"])
def claim_gift(id):
    gift = get_gift_order(id)
    parsed = shapes.validate(shapes.body(), [
        shapes.field("claim_mode", required=True, kind="enum",
                     members=C.CLAIM_MODES),
        shapes.field("service_level", kind="enum", members=C.SERVICE_LEVELS,
                     default="STANDARD"),
    ])
    registry = _registry_of(gift)
    item = _item_of(gift)
    require_registry_owner(registry["owner_account_id"] if registry else None)
    if gift["status"] != "PAID":
        raise ApiError("ERR_GIFT_ORDER_STATE_INVALID")

    mode = parsed["claim_mode"]
    # G8 — rung 41 (spacing, ITEM only) then rung 42 (claim window).
    if mode == "ITEM":
        services.check_shipment_spacing(registry["owner_account_id"])
    deadline = store.plus_days(gift["paid_at"], C.GIFT_CLAIM_WINDOW_DAYS)
    if now() > deadline:
        raise ApiError("ERR_GIFT_CLAIM_WINDOW_EXPIRED")

    sku = db.skus.get(item["sku_id"]) if item else None
    child = db.children.get(registry["child_id"]) if registry else None

    if mode == "CREDIT":
        credit = services.issue_credit(
            registry["owner_account_id"], "GIFT", int(gift["paid_cents"]), False,
            store.plus_days(now(), C.GIFT_CREDIT_EXPIRY_DAYS),
            source_gift_order_id=gift["id"])
        gift["claim_mode"] = "CREDIT"
        gift["claimed_at"] = now()
        gift["status"] = "CLAIMED_CREDIT"
        touch(gift)
        services.recompute_account_estimate(registry["owner_account_id"])
        return ok(serialize.gift_order(gift))

    # ITEM branch — G9 rungs 45, 46 then 67.
    if sku is None:
        raise ApiError("ERR_SKU_NOT_FOUND")
    if child is not None and not calc.allergen_eligible(sku, child):
        raise ApiError("ERR_ALLERGEN_BLOCKED")
    if child is not None and not calc.hypo_required_ok(sku, child):
        raise ApiError("ERR_HYPOALLERGENIC_REQUIRED")
    if int(sku["stock_packs"]) < int(gift["quantity"]):
        raise ApiError("ERR_SKU_OUT_OF_STOCK")

    # paid_cents is REWRITTEN at the claim-time SKU price.
    gift["paid_cents"] = int(gift["quantity"]) * calc.effective_unit_price(sku)
    sku["stock_packs"] = int(sku["stock_packs"]) - int(gift["quantity"])
    touch(sku)
    services.create_shipment(registry["owner_account_id"], None, gift["id"],
                             parsed["service_level"] or "STANDARD")
    gift["claim_mode"] = "ITEM"
    gift["claimed_at"] = now()
    gift["status"] = "CLAIMED_ITEM"
    touch(gift)
    return ok(serialize.gift_order(gift))


@api(bp, "POST", "/gift-orders/<id>/refund", ["GiftPurchaser", "RegistryOwner"])
def refund_gift(id):
    gift = get_gift_order(id)
    # Rung 14 first, then rung 16: only the paying GiftPurchaser may refund.
    require_gift_purchaser(gift["purchaser_account_id"])
    if g.role != "GiftPurchaser" or g.user_id != gift["purchaser_account_id"]:
        raise ApiError("ERR_PIPELINE_G_REFUND_ACTOR")
    if gift["status"] not in ("PAID", "CLAIMED_CREDIT", "CLAIMED_ITEM", "FULFILLED"):
        raise ApiError("ERR_GIFT_ORDER_STATE_INVALID")

    item = _item_of(gift)
    registry = _registry_of(gift)
    was = gift["status"]
    claim_mode = gift["claim_mode"]

    if was == "CLAIMED_ITEM":
        shipment = services.shipment_of_gift(gift["id"])
        if shipment is not None and shipment["status"] == "DELIVERED":
            raise ApiError("ERR_SHIPMENT_STATE_INVALID")

    # HOP 1 — the gift is refunded and a Pipeline-G Refund is opened for the
    # full paid face value. Pipeline G never prorates and never charges a
    # restock fee.
    gift["status"] = "REFUNDED"
    touch(gift)
    services.create_refund(gift["purchaser_account_id"], None, gift["id"],
                           "GIFT_REFUND", int(gift["paid_cents"]), 0)

    if claim_mode == "CREDIT":
        # HOPS 2..5 — revoke the derived GIFT credit and unwind the cycle that
        # had already consumed part of it.
        for credit in list(db.credits.values()):
            if credit.get("source_gift_order_id") != gift["id"]:
                continue
            services.reverse_credit_consumption_on_planned_cycles(credit)
            if credit["status"] in ("AVAILABLE", "PARTIALLY_CONSUMED"):
                services.forfeit_credit(credit, "REVOKED")
            services.recompute_account_estimate(credit["account_id"])
    elif claim_mode == "ITEM":
        shipment = services.shipment_of_gift(gift["id"])
        if shipment is not None and shipment["status"] != "RETURNED":
            shipment["status"] = "RETURNED"
            touch(shipment)
        sku = db.skus.get(item["sku_id"]) if item else None
        if sku is not None:
            sku["stock_packs"] = int(sku["stock_packs"]) + int(gift["quantity"])
            touch(sku)

    if item is not None:
        services.apply_item_fulfilment(item, -int(gift["quantity"]))
    if registry is not None:
        services.recompute_registry(registry)
    return ok(serialize.gift_order(gift))
