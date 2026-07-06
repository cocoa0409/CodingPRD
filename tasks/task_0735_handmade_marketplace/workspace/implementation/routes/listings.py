"""Listing endpoints."""
from flask import Blueprint, request
from auth import get_auth, require_role, require_shop_owner
from db import store, stamp_common, touch, parse_iso
from envelope import success
from errors import (
    raise_err, ERR_VALIDATION, ERR_LISTING_NOT_FOUND, ERR_SHOP_NOT_FOUND,
    ERR_SHIPPING_PROFILE_NOT_FOUND, ERR_MATERIAL_NOT_FOUND, ERR_INVALID_STATE,
)
from helpers import get_json_body, require_field, opt_field, parse_pagination, paginate, sort_by_created
from serializers import listing_view
from services import find_shop

bp = Blueprint("listings", __name__)

FT_VALS = {"READY_TO_SHIP", "MADE_TO_ORDER"}


def _require_listing(lid):
    l = store.listings.get(lid)
    if l is None:
        raise_err(ERR_LISTING_NOT_FOUND, "not found")
    return l


@bp.route("/seller/listings", methods=["POST"])
def create():
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    body = get_json_body()

    shop_id = require_field(body, "shop_id", str)
    sp_id = require_field(body, "shipping_profile_id", str)
    title = require_field(body, "title", str)
    ftype = require_field(body, "fulfillment_type", str)
    ptd = require_field(body, "processing_time_days", int)
    price = require_field(body, "price_cents", int)

    require_shop_owner(user_id, role, shop_id)

    # Existence checks left-to-right per PRD 2.5.
    if find_shop(shop_id) is None:
        raise_err(ERR_SHOP_NOT_FOUND, "shop not found")
    if store.shipping_profiles.get(sp_id) is None:
        raise_err(ERR_SHIPPING_PROFILE_NOT_FOUND, "shipping profile not found")
    mid = opt_field(body, "primary_material_id", str, None)
    if mid is not None and store.materials.get(mid) is None:
        raise_err(ERR_MATERIAL_NOT_FOUND, "material not found")

    if ftype not in FT_VALS:
        raise_err(ERR_VALIDATION, "invalid fulfillment_type")
    if ptd < 0:
        raise_err(ERR_VALIDATION, "processing_time_days must be >= 0")
    if price < 1:
        raise_err(ERR_VALIDATION, "price_cents must be >= 1")

    mat_qty = opt_field(body, "material_qty_per_unit", int, 0)
    if mat_qty < 0:
        raise_err(ERR_VALIDATION, "material_qty_per_unit must be >= 0")
    quantity = opt_field(body, "quantity", int, 0)
    if quantity < 0:
        raise_err(ERR_VALIDATION, "quantity must be >= 0")
    p_enabled = opt_field(body, "personalization_enabled", bool, False)
    p_required = opt_field(body, "personalization_required", bool, False)
    p_limit = opt_field(body, "personalization_char_limit", int, 256)
    if p_limit < 1 or p_limit > 1024:
        raise_err(ERR_VALIDATION, "personalization_char_limit out of range")
    variations = opt_field(body, "variations", list, [])
    # Validate variation structure
    for v in variations:
        if not isinstance(v, dict):
            raise_err(ERR_VALIDATION, "variation must be object")
        for k in ("key", "label", "price_delta_cents", "stock_qty"):
            if k not in v:
                raise_err(ERR_VALIDATION, f"variation missing {k}")
        if not isinstance(v["price_delta_cents"], int) or isinstance(v["price_delta_cents"], bool):
            raise_err(ERR_VALIDATION, "variation price_delta_cents must be int")
        if not isinstance(v["stock_qty"], int) or isinstance(v["stock_qty"], bool):
            raise_err(ERR_VALIDATION, "variation stock_qty must be int")
    expires_at_s = opt_field(body, "expires_at", str, None)
    expires_at = parse_iso(expires_at_s) if expires_at_s else None

    rec = {
        "shop_id": shop_id,
        "shipping_profile_id": sp_id,
        "primary_material_id": mid,
        "material_qty_per_unit": mat_qty,
        "title": title,
        "fulfillment_type": ftype,
        "processing_time_days": ptd,
        "price_cents": price,
        "quantity": quantity,
        "status": "DRAFT",
        "personalization_enabled": p_enabled,
        "personalization_required": p_required,
        "personalization_char_limit": p_limit,
        "variations": variations,
        "expires_at": expires_at,
    }
    stamp_common(rec)
    store.listings[rec["id"]] = rec
    return success(listing_view(rec), status=201)


@bp.route("/seller/listings/<lid>", methods=["GET"])
def fetch(lid):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin", "Buyer"})
    l = _require_listing(lid)
    # Seller ownership for GET is not strictly required by PRD for listings
    # (buyers can view). But Seller with mismatched X-User-ID:
    # PRD says ownership applies to "shop-scoped mutations" - GET is not a mutation.
    # So we don't enforce ownership on GET.
    return success(listing_view(l))


@bp.route("/seller/listings", methods=["GET"])
def list_():
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin", "Buyer"})
    limit, offset = parse_pagination()
    args = request.args
    shop_id = args.get("shop_id")
    sp_id = args.get("shipping_profile_id")
    pm_id = args.get("primary_material_id")
    status = args.get("status")
    ftype = args.get("fulfillment_type")

    items = list(store.listings.values())
    # Hide REMOVED from list; still fetchable by id.
    items = [x for x in items if x["status"] != "REMOVED"]
    if shop_id is not None:
        items = [x for x in items if x["shop_id"] == shop_id]
    if sp_id is not None:
        items = [x for x in items if x["shipping_profile_id"] == sp_id]
    if pm_id is not None:
        items = [x for x in items if x.get("primary_material_id") == pm_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if ftype is not None:
        items = [x for x in items if x["fulfillment_type"] == ftype]
    items = sort_by_created(items)
    page, pmeta = paginate(items, limit, offset)
    return success([listing_view(x) for x in page], response_type="array", pagination=pmeta)


@bp.route("/seller/listings/<lid>/publish", methods=["POST"])
def publish(lid):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    l = _require_listing(lid)
    require_shop_owner(user_id, role, l["shop_id"])
    if l["status"] not in ("DRAFT", "INACTIVE"):
        raise_err(ERR_INVALID_STATE, "listing not in DRAFT or INACTIVE")
    shop = store.shops.get(l["shop_id"])
    if shop is None or shop["status"] not in ("ACTIVE", "VACATION"):
        raise_err(ERR_INVALID_STATE, "owning shop must be ACTIVE or VACATION")
    if l["fulfillment_type"] == "READY_TO_SHIP" and l["quantity"] < 1:
        raise_err(ERR_INVALID_STATE, "READY_TO_SHIP requires quantity >= 1")
    l["status"] = "ACTIVE"
    touch(l)
    return success(listing_view(l))


@bp.route("/seller/listings/<lid>/deactivate", methods=["POST"])
def deactivate(lid):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    l = _require_listing(lid)
    require_shop_owner(user_id, role, l["shop_id"])
    body = get_json_body()
    remove = opt_field(body, "remove", bool, False)
    if remove:
        if l["status"] not in ("ACTIVE", "INACTIVE", "SOLD_OUT"):
            raise_err(ERR_INVALID_STATE, "cannot remove from this state")
        l["status"] = "REMOVED"
    else:
        if l["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE, "listing not ACTIVE")
        l["status"] = "INACTIVE"
    touch(l)
    return success(listing_view(l))


@bp.route("/seller/listings/<lid>/restock", methods=["POST"])
def restock(lid):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    l = _require_listing(lid)
    require_shop_owner(user_id, role, l["shop_id"])
    if l["status"] != "SOLD_OUT":
        raise_err(ERR_INVALID_STATE, "listing not SOLD_OUT")
    body = get_json_body()
    restock_qty = opt_field(body, "restock_qty", int, 0)
    if l["fulfillment_type"] == "READY_TO_SHIP":
        # resulting quantity must be >= 1
        if not isinstance(restock_qty, int) or restock_qty < 0:
            raise_err(ERR_VALIDATION, "restock_qty must be non-negative int")
        l["quantity"] += restock_qty
        if l["quantity"] < 1:
            raise_err(ERR_INVALID_STATE, "resulting quantity must be >= 1")
    else:  # MADE_TO_ORDER
        mid = l.get("primary_material_id")
        if mid:
            m = store.materials.get(mid)
            if m is None or m["status"] == "OUT_OF_STOCK":
                raise_err(ERR_INVALID_STATE, "primary material must not be OUT_OF_STOCK")
    l["status"] = "ACTIVE"
    touch(l)
    return success(listing_view(l))
