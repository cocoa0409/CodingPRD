"""Part endpoints."""

from flask import Blueprint, request

import errors
from db import store, new_id, now_iso, touch
from middleware import (
    authenticate, require_roles, json_body, need, as_str, as_int, as_bool,
    pagination_params, paginate,
)
from response import success, success_list
from services import obsolete_part_cascade

bp = Blueprint("parts", __name__)

READ_ROLES = ["DistributorAdmin", "RouteDriver", "WarehouseOperator"]


def serialize(part):
    return {
        "id": part["id"],
        "sku": part["sku"],
        "description": part["description"],
        "status": part["status"],
        "is_critical": part["is_critical"],
        "unit_price_cents": part["unit_price_cents"],
        "total_stock_qty": part["total_stock_qty"],
        "reserved_qty": part["reserved_qty"],
        "available_qty": part["available_qty"],
        "created_at": part["created_at"],
        "updated_at": part["updated_at"],
        "version": part["version"],
    }


@bp.post("/vmi/parts")
def create_part():
    role = authenticate()
    body = json_body()
    sku = as_str(need(body, "sku"), "sku")
    description = as_str(need(body, "description"), "description")
    is_critical = False
    if "is_critical" in body:
        is_critical = as_bool(body["is_critical"], "is_critical")
    unit_price_cents = as_int(need(body, "unit_price_cents"), "unit_price_cents")
    if unit_price_cents < 1:
        raise errors.invalid_request("unit_price_cents must be >= 1")
    total_stock_qty = as_int(need(body, "total_stock_qty"), "total_stock_qty")
    if total_stock_qty < 0:
        raise errors.invalid_request("total_stock_qty must be >= 0")
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        if any(p["sku"] == sku for p in store.parts.values()):
            raise errors.duplicate("sku already in use")
        ts = now_iso()
        part = {
            "id": new_id(),
            "sku": sku,
            "description": description,
            "status": "ACTIVE",
            "is_critical": is_critical,
            "unit_price_cents": unit_price_cents,
            "total_stock_qty": total_stock_qty,
            "reserved_qty": 0,
            "available_qty": total_stock_qty,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
            "_seq": store.next_seq(),
        }
        store.parts[part["id"]] = part
        return success(serialize(part), 201)


@bp.get("/vmi/parts/<pid>")
def get_part(pid):
    role = authenticate()
    require_roles(role, READ_ROLES)
    part = store.parts.get(pid)
    if part is None:
        raise errors.not_found("part not found")
    return success(serialize(part), 200)


@bp.get("/vmi/parts")
def list_parts():
    role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = pagination_params()
    status = request.args.get("status")
    items = sorted(store.parts.values(), key=lambda p: p["_seq"])
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(p) for p in page], total, limit, offset)


@bp.post("/vmi/parts/<pid>/obsolete")
def obsolete_part(pid):
    role = authenticate()
    json_body(required=False)
    require_roles(role, ["DistributorAdmin"])
    with store.lock:
        part = store.parts.get(pid)
        if part is None:
            raise errors.not_found("part not found")
        if part["status"] != "ACTIVE":
            raise errors.invalid_state("part is not ACTIVE")
        # Preconditions: no live orders, no in-flight kit jobs listing the part.
        if any(
            o["part_id"] == pid and o["status"] in ("CONFIRMED", "IN_TRANSIT")
            for o in store.orders.values()
        ):
            raise errors.invalid_state(
                "part has replenishment orders in CONFIRMED or IN_TRANSIT"
            )
        if any(
            pid in j["component_part_ids"] and j["status"] in ("PICKING", "ON_HOLD")
            for j in store.kitjobs.values()
        ):
            raise errors.invalid_state(
                "part is listed on a kit job in PICKING or ON_HOLD"
            )
        part["status"] = "OBSOLETE"
        touch(part)
        obsolete_part_cascade(part)
        return success(serialize(part), 200)
