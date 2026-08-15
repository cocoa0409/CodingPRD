"""BulkInstallation and ReplenishmentOrder endpoints (PRD §3.8)."""
from datetime import timedelta

from flask import Blueprint

from constants import (
    INSTALLATION_STATUSES,
    MIN_REPLENISHMENT_GAP_HOURS,
    PRODUCTS,
    REPLENISHMENT_STATUSES,
)
from db import store
from errors import (
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_INSTALLATION_INVALID_STATE,
    ERR_REPLENISHMENT_INVALID_STATE,
    ERR_REPLENISHMENT_WINDOW_CONFLICT,
    ERR_STALE_VERSION,
    ApiError,
    bad_request,
    not_found,
)
from middleware import ANY_ROLE, get_body, locked, req_enum, req_int, req_str, require_roles
from response import success
from routes.listing import list_response
from services import calc
from services.ops import base_record, installation_out, post_reading, repl_order_out
from util import clock_now, dec, is_int, parse_instant, touch

bp = Blueprint("installations", __name__)


@bp.post("/api/bulk-installations")
@locked
def create_installation():
    uid, _ = require_roles("PlantManager")
    body = get_body()
    customer_id = req_str(body, "customer_id")
    product = req_enum(body, "product_code", PRODUCTS)
    capacity = req_int(body, "capacity_liters")
    initial = req_int(body, "initial_level_liters")
    reorder = req_int(body, "reorder_point_liters")
    max_qty = req_int(body, "max_order_qty_liters")
    if capacity <= 0:
        bad_request("capacity_liters must be > 0")
    if initial < 0 or initial > capacity:
        bad_request("initial_level_liters must be within [0, capacity_liters]")
    if reorder < 0 or reorder > capacity:
        bad_request("reorder_point_liters must be within [0, capacity_liters]")
    if max_qty <= 0:
        bad_request("max_order_qty_liters must be > 0")
    customer = store.customers.get(customer_id)
    if customer is None:
        not_found("customer not found")
    i = base_record()
    i.update(
        {
            "customer_id": customer_id,
            "product_code": product,
            "capacity_liters": capacity,
            "initial_level_liters": initial,
            "reorder_point_liters": reorder,
            "max_order_qty_liters": max_qty,
            "status": "PROPOSED",
        }
    )
    store.installations[i["id"]] = i
    post_reading(None, i["id"], dec(initial), clock_now(), "INITIAL_LOAD", uid)
    return success(installation_out(i), status=201)


@bp.get("/api/bulk-installations")
@locked
def list_installations():
    require_roles(*ANY_ROLE)
    return list_response(
        store.installations.values(),
        installation_out,
        [("customer_id", "customer_id"), ("status", "status")],
    )


def _get_installation(installationId):
    i = store.installations.get(installationId)
    if i is None:
        not_found("installation not found")
    return i


@bp.get("/api/bulk-installations/<installationId>")
@locked
def get_installation(installationId):
    require_roles(*ANY_ROLE)
    return success(installation_out(_get_installation(installationId)))


@bp.post("/api/bulk-installations/<installationId>/set-status")
@locked
def installation_set_status(installationId):
    require_roles("PlantManager")
    body = get_body()
    target = req_enum(body, "target_status", INSTALLATION_STATUSES)
    i = _get_installation(installationId)
    allowed = {
        "PROPOSED": {"INSTALLED"},
        "INSTALLED": {"ACTIVE", "DECOMMISSIONED"},
        "ACTIVE": {"PAUSED", "DECOMMISSIONED"},
        "PAUSED": {"ACTIVE", "DECOMMISSIONED"},
    }
    if target not in allowed.get(i["status"], set()):
        raise ApiError(ERR_INSTALLATION_INVALID_STATE, 409, "target_status unreachable from current installation state")
    if target == "ACTIVE" and i["status"] == "PAUSED":
        customer = store.customers.get(i["customer_id"])
        if customer is None or customer["status"] != "ACTIVE":
            raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409, "owning customer is not ACTIVE")
    if target == "DECOMMISSIONED":
        for o in store.repl_orders.values():
            if o["installation_id"] == i["id"] and o["status"] == "PENDING":
                o["status"] = "CANCELLED"
                touch(o)
    i["status"] = target
    touch(i)
    return success(installation_out(i))


# ---------------- replenishment orders ----------------

@bp.post("/api/replenishment-orders")
@locked
def create_repl_order():
    require_roles("LogisticsCoordinator")
    body = get_body()
    installation_id = req_str(body, "installation_id")
    scheduled = parse_instant(body.get("scheduled_delivery_at"))
    if scheduled is None:
        bad_request("scheduled_delivery_at must be a valid ISO 8601 instant")
    expected = body.get("expected_installation_version")
    if expected is None or not is_int(expected):
        bad_request("expected_installation_version is required and must be an integer")
    inst = store.installations.get(installation_id)
    if inst is None:
        not_found("installation not found")
    if expected != inst["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "installation version is stale")
    if inst["status"] != "ACTIVE":
        raise ApiError(ERR_INSTALLATION_INVALID_STATE, 409, "installation must be ACTIVE")
    delivered = [
        o for o in store.repl_orders.values()
        if o["installation_id"] == inst["id"] and o["status"] == "DELIVERED"
    ]
    if delivered:
        last = max(delivered, key=lambda o: (o["delivered_at_dt"], o["_seq"]))
        if scheduled < last["delivered_at_dt"] + timedelta(hours=MIN_REPLENISHMENT_GAP_HOURS):
            raise ApiError(
                ERR_REPLENISHMENT_WINDOW_CONFLICT,
                409,
                "scheduled_delivery_at violates the 24h spacing rule",
            )
    qty = calc.replenishment_qty(inst)
    if qty <= 0:
        bad_request("requested replenishment quantity would be <= 0")
    o = base_record()
    o.update(
        {
            "installation_id": inst["id"],
            "scheduled_delivery_at_dt": scheduled,
            "requested_qty_liters": qty,
            "delivered_at_dt": None,
            "superseded_by_order_id": None,
            "status": "PENDING",
        }
    )
    store.repl_orders[o["id"]] = o
    for old in store.repl_orders.values():
        if old["id"] != o["id"] and old["installation_id"] == inst["id"] and old["status"] == "PENDING":
            old["status"] = "SUPERSEDED"
            old["superseded_by_order_id"] = o["id"]
            touch(old)
    touch(inst)
    return success(repl_order_out(o), status=201)


@bp.get("/api/replenishment-orders")
@locked
def list_repl_orders():
    require_roles(*ANY_ROLE)
    return list_response(
        store.repl_orders.values(),
        repl_order_out,
        [("installation_id", "installation_id"), ("status", "status")],
    )


@bp.get("/api/replenishment-orders/<orderId>")
@locked
def get_repl_order(orderId):
    require_roles(*ANY_ROLE)
    o = store.repl_orders.get(orderId)
    if o is None:
        not_found("replenishment order not found")
    return success(repl_order_out(o))


@bp.post("/api/replenishment-orders/<orderId>/set-status")
@locked
def repl_set_status(orderId):
    uid, _ = require_roles("LogisticsCoordinator")
    body = get_body()
    target = req_enum(body, "target_status", REPLENISHMENT_STATUSES)
    o = store.repl_orders.get(orderId)
    if o is None:
        not_found("replenishment order not found")
    if target not in ("DELIVERED", "CANCELLED"):
        bad_request("target_status not supported by set-status")
    if o["status"] != "PENDING":
        raise ApiError(ERR_REPLENISHMENT_INVALID_STATE, 409, "order must be PENDING")
    if target == "CANCELLED":
        o["status"] = "CANCELLED"
        touch(o)
        return success(repl_order_out(o))
    # DELIVERED
    inst = store.installations[o["installation_id"]]
    now = clock_now()
    o["status"] = "DELIVERED"
    o["delivered_at_dt"] = now
    new_level = calc.installation_current_level(inst) + o["requested_qty_liters"]
    cap = dec(inst["capacity_liters"])
    if new_level > cap:
        new_level = cap
    post_reading(None, inst["id"], new_level, now, "SYSTEM_REPLENISHMENT", uid)
    touch(o)
    touch(inst)
    return success(repl_order_out(o))
