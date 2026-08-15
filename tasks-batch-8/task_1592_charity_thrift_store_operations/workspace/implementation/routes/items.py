"""DonationItem endpoints (PRD §3.2, §3.3)."""
from datetime import timedelta

from flask import Blueprint

from db import db, touch, iso_now, format_ts
from errors import (
    ApiError, not_found, invalid_request,
    ERR_BATCH_INVALID_STATE, ERR_ITEM_INVALID_STATE, ERR_GUIDELINE_MISSING,
    ERR_HIGH_VALUE_NEEDS_MANAGER, ERR_NO_OPEN_CYCLE,
)
from middleware import require_roles, get_body, ALL_ROLES, paginate, query_filters, apply_filters
from response import success_object, success_list
from services import calc
from services.helpers import (
    get_open_cycle, recompute_batch_rollups, assign_item_to_bale,
)

bp = Blueprint("items", __name__)

ITEM_CATEGORIES = ["CLOTHING", "FURNITURE", "ELECTRONICS", "HOUSEWARES",
                   "BOOKS_MEDIA", "TOYS", "COLLECTIBLES"]
SALVAGE_CATEGORIES = ["TEXTILES", "PAPER", "EWASTE", "BULK"]


def item_view(i):
    return dict(i)


def _get_item(item_id):
    i = db.items.get(item_id)
    if i is None:
        raise not_found("item")
    return i


@bp.route("/api/items/<item_id>", methods=["GET"])
def get_item(item_id):
    require_roles(ALL_ROLES)
    return success_object(item_view(_get_item(item_id)))


@bp.route("/api/items", methods=["GET"])
def list_items():
    require_roles(ALL_ROLES)
    filters = query_filters(["batch_id", "sale_id", "bale_id", "floor_cycle_id",
                             "shrunk_cycle_id", "status", "category"])
    records = apply_filters(list(db.items.values()), filters)
    page, limit, offset, total = paginate(records)
    return success_list([item_view(i) for i in page], limit, offset, total)


@bp.route("/api/items/<item_id>/triage", methods=["POST"])
def triage_item(item_id):
    require_roles(["IntakeAttendant"])
    payload = get_body(
        required=[("decision", "string")],
        optional=[("salvage_category", "string"), ("weight_lbs", "number"),
                  ("appraisal_confirmed", "boolean")],
        enums={"decision": ["SALABLE", "RECYCLE", "SALVAGE"],
               "salvage_category": SALVAGE_CATEGORIES},
    )
    item = _get_item(item_id)
    batch = db.batches.get(item["batch_id"])
    if item["status"] != "RECEIVED":
        raise ApiError(ERR_ITEM_INVALID_STATE, 409,
                       "triage requires an item in RECEIVED")
    if batch is None or batch["status"] != "SORTING":
        raise ApiError(ERR_BATCH_INVALID_STATE, 409,
                       "triage is accepted only while the owning batch is SORTING")
    decision = payload["decision"]

    if decision == "RECYCLE":
        # salvage_category + weight_lbs required (payload or intake)
        salvage_category = payload.get("salvage_category")
        if not salvage_category:
            raise invalid_request("salvage_category is required for RECYCLE triage")
        weight = payload.get("weight_lbs")
        if weight is None:
            weight = item.get("weight_lbs")
        if weight is None:
            raise invalid_request("weight_lbs is required for RECYCLE triage")
        if float(weight) <= 0:
            raise invalid_request("weight_lbs must be positive")
        item["weight_lbs"] = weight
        item["salvage_category"] = salvage_category
        item["status"] = "RECYCLE"
        assign_item_to_bale(item, salvage_category)
    elif decision == "SALVAGE":
        item["status"] = "SALVAGE"
    else:  # SALABLE
        item["status"] = "SALABLE"

    item["appraisal_confirmed"] = payload.get("appraisal_confirmed", False)
    touch(item)
    recompute_batch_rollups(batch)
    touch(batch)
    return success_object(item_view(item))


@bp.route("/api/items/<item_id>/price", methods=["POST"])
def price_item(item_id):
    user_id, role = require_roles(["Pricer", "StoreManager"])
    get_body()
    item = _get_item(item_id)
    if item["status"] != "SALABLE":
        raise ApiError(ERR_ITEM_INVALID_STATE, 409,
                       "pricing requires an item in SALABLE")
    # guideline lookup (referential)
    guideline = None
    for g in db.guidelines.values():
        if g["category"] == item["category"] and g["status"] == "ACTIVE":
            guideline = g
            break
    if guideline is None:
        raise ApiError(ERR_GUIDELINE_MISSING, 422,
                       "No ACTIVE PricingGuideline for the item's category")
    price = calc.calc_suggested_price(item["category"], item["condition"], guideline)
    # shrink-alert gate (priority 8): alert ON + price >= 10000 -> manager only
    open_cycle = get_open_cycle()
    if open_cycle is not None and open_cycle.get("shrink_alert_active") \
            and price >= calc.HIGH_VALUE_PRICE_CENTS and role != "StoreManager":
        raise ApiError(ERR_HIGH_VALUE_NEEDS_MANAGER, 422,
                       "Shrink-alert active and computed price >= 10000 cents; "
                       "a StoreManager must price this item")
    item["base_price_cents"] = price
    item["current_price_cents"] = price
    item["priced_at"] = iso_now()
    item["markdown_round"] = 0
    item["status"] = "PRICED"
    touch(item)
    return success_object(item_view(item))


@bp.route("/api/items/<item_id>/to-floor", methods=["POST"])
def to_floor(item_id):
    require_roles(["Pricer"])
    get_body()
    item = _get_item(item_id)
    if item["status"] != "PRICED":
        raise ApiError(ERR_ITEM_INVALID_STATE, 409,
                       "to-floor requires an item in PRICED")
    open_cycle = get_open_cycle()
    if open_cycle is None:
        raise ApiError(ERR_NO_OPEN_CYCLE, 409,
                       "to-floor requires an OPEN weekly cycle")
    item["status"] = "ON_FLOOR"
    item["floor_cycle_id"] = open_cycle["id"]
    item["tag_color"] = open_cycle["rotation_color"]
    touch(item)
    return success_object(item_view(item))


@bp.route("/api/items/<item_id>/hold", methods=["POST"])
def hold_item(item_id):
    require_roles(["Pricer"])
    get_body()
    item = _get_item(item_id)
    if item["status"] != "ON_FLOOR":
        raise ApiError(ERR_ITEM_INVALID_STATE, 409,
                       "hold requires an item in ON_FLOOR")
    expires = db.clock.now() + timedelta(hours=calc.HOLD_HOURS)
    item["status"] = "ON_HOLD"
    item["hold_expires_at"] = format_ts(expires)
    touch(item)
    return success_object(item_view(item))


@bp.route("/api/items/<item_id>/release-hold", methods=["POST"])
def release_hold(item_id):
    require_roles(["Pricer"])
    get_body()
    item = _get_item(item_id)
    if item["status"] != "ON_HOLD":
        raise ApiError(ERR_ITEM_INVALID_STATE, 409,
                       "release-hold requires an item in ON_HOLD")
    item["status"] = "ON_FLOOR"
    item["hold_expires_at"] = None
    touch(item)
    return success_object(item_view(item))


@bp.route("/api/items/<item_id>/shrink", methods=["POST"])
def shrink_item(item_id):
    require_roles(["StoreManager"])
    payload = get_body(
        required=[("reason", "string")],
        enums={"reason": ["THEFT", "DAMAGE", "LOSS"]},
    )
    item = _get_item(item_id)
    if item["status"] not in ("SALABLE", "PRICED", "ON_FLOOR", "ON_HOLD"):
        raise ApiError(ERR_ITEM_INVALID_STATE, 409,
                       "shrink requires an item in SALABLE, PRICED, ON_FLOOR, or ON_HOLD")
    open_cycle = get_open_cycle()
    if open_cycle is None:
        raise ApiError(ERR_NO_OPEN_CYCLE, 409,
                       "shrink requires an OPEN weekly cycle")
    if item.get("current_price_cents") is not None:
        item["value_at_shrink_cents"] = item["current_price_cents"]
    else:
        item["value_at_shrink_cents"] = item["provisional_value_cents"]
    item["shrunk_cycle_id"] = open_cycle["id"]
    item["shrink_reason"] = payload["reason"]
    item["hold_expires_at"] = None
    item["status"] = "SHRUNK"
    touch(item)
    return success_object(item_view(item))
