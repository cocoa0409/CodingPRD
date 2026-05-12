"""Stores: POST /stores, GET /stores, GET /stores/{id}, PATCH /stores/{id}."""

from flask import Blueprint

import clock
import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("stores", __name__, url_prefix="/supply-chain/stores")


VALID_ZONES_STORE = {"AMBIENT", "CHILLED", "FROZEN", "MIXED"}


def _validate_create_payload(body):
    required = [
        "store_code",
        "name",
        "temperature_zone",
        "catalog_permission",
        "order_window_open_minute",
        "order_window_close_minute",
    ]
    for f in required:
        if f not in body:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Missing field: {f}")

    zone = body["temperature_zone"]
    if zone not in VALID_ZONES_STORE:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Invalid temperature_zone: {zone}")

    catalog = body["catalog_permission"]
    if not isinstance(catalog, list):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "catalog_permission must be an array.")

    open_min = body["order_window_open_minute"]
    close_min = body["order_window_close_minute"]
    if not isinstance(open_min, int) or not (0 <= open_min <= 1439):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "order_window_open_minute must be 0..1439.")
    if not isinstance(close_min, int) or not (0 <= close_min <= 1439):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "order_window_close_minute must be 0..1439.")
    if close_min <= open_min:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "order_window_close_minute must be > open.")


@bp.route("", methods=["POST"])
@auth_required("PlatformAdmin")
def create_store():
    body = helpers.get_json_body()
    _validate_create_payload(body)

    # Validate every recipe in catalog_permission exists.
    for rid in body["catalog_permission"]:
        if rid not in db.recipes:
            errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, f"Recipe {rid} not found.")

    sid = db.new_id()
    common = helpers.common_create()
    store = {
        "id": sid,
        "store_code": body["store_code"],
        "name": body["name"],
        "temperature_zone": body["temperature_zone"],
        "catalog_permission": list(body["catalog_permission"]),
        "order_window_open_minute": body["order_window_open_minute"],
        "order_window_close_minute": body["order_window_close_minute"],
        "cutoff_minutes_before_close": body.get("cutoff_minutes_before_close", 60),
        "low_amount_bypass_cents": body.get("low_amount_bypass_cents", 50000),
        "avg_daily_sales_cents": body.get("avg_daily_sales_cents", 0),
        "status": "ACTIVE",
        **common,
    }
    db.stores[sid] = store
    audit.append(target_type="Store", target_id=sid, action="CREATE_STORE",
                 payload={"store_code": store["store_code"]})
    return response.created(serializers.store_dict(store))


@bp.route("", methods=["GET"])
@auth_required("PlatformAdmin", "CentralKitchenPlanner", "FinanceController")
def list_stores():
    from flask import request
    limit, offset = helpers.parse_pagination()
    items = list(db.stores.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [s for s in items if s["status"] == status_filter]
    items.sort(key=lambda s: s["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.store_dict(s) for s in page],
                            limit=limit, offset=offset, total_count=total)


@bp.route("/<sid>", methods=["GET"])
@auth_required("PlatformAdmin", "CentralKitchenPlanner", "FinanceController", "StoreManager")
def read_store(sid):
    from flask import g
    store = db.stores.get(sid)
    if store is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Store {sid} not found.")
    if g.user_role == "StoreManager" and g.user_id != store["id"]:
        errors.raise_error(errors.ERR_FORBIDDEN, "StoreManager may only read their own store.")
    return response.ok(serializers.store_dict(store))


@bp.route("/<sid>", methods=["PATCH"])
@auth_required("PlatformAdmin")
def update_store(sid):
    body = helpers.get_json_body()
    store = db.stores.get(sid)
    if store is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Store {sid} not found.")
    helpers.check_occ(store, body.get("version"))

    updatable = [
        "catalog_permission",
        "order_window_open_minute",
        "order_window_close_minute",
        "cutoff_minutes_before_close",
        "low_amount_bypass_cents",
    ]

    if "catalog_permission" in body:
        cp = body["catalog_permission"]
        if not isinstance(cp, list):
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "catalog_permission must be an array.")
        for rid in cp:
            if rid not in db.recipes:
                errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, f"Recipe {rid} not found.")
        store["catalog_permission"] = list(cp)

    new_open = body.get("order_window_open_minute", store["order_window_open_minute"])
    new_close = body.get("order_window_close_minute", store["order_window_close_minute"])
    if not isinstance(new_open, int) or not (0 <= new_open <= 1439):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "order_window_open_minute must be 0..1439.")
    if not isinstance(new_close, int) or not (0 <= new_close <= 1439):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "order_window_close_minute must be 0..1439.")
    if new_close <= new_open:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "order_window_close_minute must be > open.")
    store["order_window_open_minute"] = new_open
    store["order_window_close_minute"] = new_close

    if "cutoff_minutes_before_close" in body:
        store["cutoff_minutes_before_close"] = body["cutoff_minutes_before_close"]
    if "low_amount_bypass_cents" in body:
        store["low_amount_bypass_cents"] = body["low_amount_bypass_cents"]

    helpers.bump(store)
    audit.append(target_type="Store", target_id=sid, action="UPDATE_STORE",
                 payload={k: store[k] for k in updatable})
    return response.ok(serializers.store_dict(store))
