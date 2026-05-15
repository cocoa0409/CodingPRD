"""Warehouse + InventoryLot endpoints (AdminOps only)."""
from __future__ import annotations

from flask import Blueprint, request

from app.auth import require_role
from app.errors import api_error
from app.pagination import paginate, parse_pagination, sort_by_created_at
from app.response import success_array, success_object
from app.store import store
from app.utils import is_int, is_nonempty_str, logical_now_iso, new_id, parse_iso_date


bp = Blueprint("warehouses", __name__)


@bp.route("/warehouses", methods=["POST"])
@require_role("AdminOps")
def create_warehouse(user_id: str, role: str):
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    code = body.get("code")
    serves = body.get("serves_regions")
    rank = body.get("priority_rank")
    cap = body.get("daily_outbound_capacity")
    if not is_nonempty_str(code):
        raise api_error("ERR_INVALID_REQUEST", "code required")
    if not isinstance(serves, list) or not serves or not all(isinstance(x, str) for x in serves):
        raise api_error("ERR_INVALID_REQUEST", "serves_regions must be non-empty list of strings")
    if not is_int(rank) or not (1 <= int(rank) <= 100):
        raise api_error("ERR_INVALID_REQUEST", "priority_rank must be int 1..100")
    if not is_int(cap) or int(cap) < 1:
        raise api_error("ERR_INVALID_REQUEST", "daily_outbound_capacity must be int >= 1")
    wid = new_id()
    now = logical_now_iso()
    wh = {
        "id": wid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "code": code,
        "serves_regions": list(serves),
        "priority_rank": int(rank),
        "daily_outbound_capacity": int(cap),
        "status": "ONLINE",
    }
    store.warehouses[wid] = wh
    return success_object(wh, status=201)


@bp.route("/warehouses", methods=["GET"])
@require_role("AdminOps")
def list_warehouses(user_id: str, role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(store.warehouses.values()))
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)


@bp.route("/warehouses/<wid>", methods=["PATCH"])
@require_role("AdminOps")
def update_warehouse(wid, user_id: str, role: str):
    wh = store.warehouses.get(wid)
    if not wh:
        raise api_error("ERR_WAREHOUSE_NOT_FOUND", "Warehouse not found")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    if "version" in body:
        if not is_int(body["version"]):
            raise api_error("ERR_INVALID_REQUEST", "version must be integer")
        if body["version"] != wh["version"]:
            raise api_error("ERR_VERSION_CONFLICT", "version mismatch")
    if "status" in body:
        if body["status"] not in ("ONLINE", "OFFLINE"):
            raise api_error("ERR_INVALID_REQUEST", "status must be ONLINE or OFFLINE")
        wh["status"] = body["status"]
    if "daily_outbound_capacity" in body:
        if not is_int(body["daily_outbound_capacity"]) or int(body["daily_outbound_capacity"]) < 1:
            raise api_error("ERR_INVALID_REQUEST", "daily_outbound_capacity invalid")
        wh["daily_outbound_capacity"] = int(body["daily_outbound_capacity"])
    if "priority_rank" in body:
        pr = body["priority_rank"]
        if not is_int(pr) or not (1 <= int(pr) <= 100):
            raise api_error("ERR_INVALID_REQUEST", "priority_rank invalid")
        wh["priority_rank"] = int(pr)
    wh["updated_at"] = logical_now_iso()
    wh["version"] = wh.get("version", 1) + 1
    return success_object(wh)


@bp.route("/warehouses/<wid>/inventory-lots", methods=["POST"])
@require_role("AdminOps")
def create_lot(wid, user_id: str, role: str):
    wh = store.warehouses.get(wid)
    if not wh:
        raise api_error("ERR_WAREHOUSE_NOT_FOUND", "Warehouse not found")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    rid = body.get("recipe_id")
    batch = body.get("batch_code")
    exp = body.get("expiration_date")
    qty = body.get("quantity_grams")
    if not is_nonempty_str(rid) or rid not in store.recipes:
        raise api_error("ERR_RECIPE_NOT_FOUND", "Recipe not found")
    if not is_nonempty_str(batch):
        raise api_error("ERR_INVALID_REQUEST", "batch_code required")
    if not is_nonempty_str(exp) or parse_iso_date(exp) is None:
        raise api_error("ERR_INVALID_REQUEST", "expiration_date must be ISO date YYYY-MM-DD")
    if not is_int(qty) or int(qty) < 0:
        raise api_error("ERR_INVALID_REQUEST", "quantity_grams must be integer >= 0")
    # Uniqueness check
    for lot in store.inventory_lots.values():
        if (
            lot["warehouse_id"] == wid
            and lot["recipe_id"] == rid
            and lot["batch_code"] == batch
        ):
            raise api_error("ERR_INVALID_REQUEST", "Duplicate batch_code for (warehouse, recipe)")
    lid = new_id()
    now = logical_now_iso()
    lot = {
        "id": lid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "warehouse_id": wid,
        "recipe_id": rid,
        "batch_code": batch,
        "expiration_date": exp,
        "quantity_grams": int(qty),
    }
    store.inventory_lots[lid] = lot
    return success_object(lot, status=201)


@bp.route("/warehouses/<wid>/inventory-lots", methods=["GET"])
@require_role("AdminOps")
def list_lots(wid, user_id: str, role: str):
    wh = store.warehouses.get(wid)
    if not wh:
        raise api_error("ERR_WAREHOUSE_NOT_FOUND", "Warehouse not found")
    limit, offset = parse_pagination()
    rid = request.args.get("recipe_id")
    items = [l for l in store.inventory_lots.values() if l["warehouse_id"] == wid]
    if rid:
        items = [l for l in items if l["recipe_id"] == rid]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)
