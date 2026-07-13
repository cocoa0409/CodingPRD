"""GWP, SAMPLE and BUNDLE promotions."""
from flask import Blueprint, request

from db import base_record, db, public
from errors import invalid
from middleware import (
    as_enum,
    as_int,
    as_number,
    as_str,
    authenticate,
    body,
    get_promotion,
    get_variant,
    page,
    pagination,
    required,
)
from response import created, ok, ok_list

bp = Blueprint("promotions", __name__)

PROMO_TYPES = ("GWP", "SAMPLE", "BUNDLE")
PROMO_STATUS = ("ACTIVE", "ENDED")


@bp.post("/promotions")
def create_promotion():
    authenticate("MerchandisingAdmin")
    payload = body()

    name = as_str(required(payload, "name"), "name")
    promo_type = as_enum(required(payload, "promo_type"), "promo_type", PROMO_TYPES)

    threshold = payload.get("threshold_cents")
    threshold = as_int(threshold, "threshold_cents", minimum=0) if threshold is not None else 0

    gift_quantity = payload.get("gift_quantity")
    gift_quantity = as_int(gift_quantity, "gift_quantity", minimum=1) if gift_quantity is not None else 1

    discount_pct = payload.get("bundle_discount_pct")
    discount_pct = as_number(discount_pct, "bundle_discount_pct", minimum=0, exclusive_max=1) if discount_pct is not None else 0

    priority = payload.get("priority")
    priority = as_int(priority, "priority") if priority is not None else 100

    status = payload.get("status")
    status = as_enum(status, "status", PROMO_STATUS) if status is not None else "ACTIVE"

    gift_variant_id = payload.get("gift_variant_id")
    if gift_variant_id is not None:
        gift_variant_id = as_str(gift_variant_id, "gift_variant_id")

    bundle_variant_ids = payload.get("bundle_variant_ids")
    if bundle_variant_ids is not None:
        if not isinstance(bundle_variant_ids, list) or any(not isinstance(v, str) for v in bundle_variant_ids):
            raise invalid("'bundle_variant_ids' must be an array of variant ids")
    else:
        bundle_variant_ids = [] if promo_type == "BUNDLE" else None

    # body-reference existence
    if gift_variant_id is not None:
        get_variant(gift_variant_id)
    for variant_id in (bundle_variant_ids or []):
        get_variant(variant_id)

    promotion = base_record()
    promotion.update({
        "name": name,
        "promo_type": promo_type,
        "threshold_cents": threshold,
        "gift_variant_id": gift_variant_id,
        "gift_quantity": gift_quantity,
        "bundle_variant_ids": bundle_variant_ids,
        "bundle_discount_pct": discount_pct,
        "priority": priority,
        "status": status,
    })
    db.promotions[promotion["id"]] = promotion
    return created(public(promotion))


@bp.get("/promotions/<promotion_id>")
def read_promotion(promotion_id):
    authenticate("MerchandisingAdmin", "StoreAssociate", "Customer")
    return ok(public(get_promotion(promotion_id)))


@bp.get("/promotions")
def list_promotions():
    authenticate("MerchandisingAdmin", "StoreAssociate", "Customer")
    limit, offset = pagination()
    gift_variant_id = request.args.get("gift_variant_id")
    promo_type = request.args.get("promo_type")

    records = list(db.promotions.values())
    if gift_variant_id:
        records = [p for p in records if p["gift_variant_id"] == gift_variant_id]
    if promo_type:
        records = [p for p in records if p["promo_type"] == promo_type]
    items, total = page(records, limit, offset, public)
    return ok_list(items, limit, offset, total)
