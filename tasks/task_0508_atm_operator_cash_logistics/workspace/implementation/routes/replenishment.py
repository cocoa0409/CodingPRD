"""Replenishment-order routes: create, read/list, dispatch, confirm-load, recall."""
from flask import Blueprint, request

import lookups
import serialize
import validate
import services.replenishment as repl_svc
from constants import FORECAST_BASES
from db import store
from errors import err
from middleware import authenticate, authorize
from response import ok_array, ok_object
from util import parse_iso

bp = Blueprint("replenishment", __name__)


@bp.route("/replenishment-orders", methods=["POST"])
def create_order():
    _, role = authenticate()
    authorize(role, {"VaultController", "PlatformAdmin"})
    body = validate.get_body()
    atm_id = validate.require_str(body, "atm_id")
    route_id = validate.require_str(body, "route_id")
    amount = validate.require_int(body, "order_amount_cents")
    window_start = validate.require_str(body, "service_window_start")
    window_end = validate.require_str(body, "service_window_end")
    basis = validate.optional_enum(body, "forecast_basis", FORECAST_BASES, "FORWARD")
    # FK existence.
    lookups.atm(store, atm_id)
    lookups.route(store, route_id)
    # Well-typed datetimes.
    if parse_iso(window_start) is None or parse_iso(window_end) is None:
        raise err("ERR_INVALID_REQUEST", "service window must be ISO 8601 instants.")
    order = {
        "atm_id": atm_id,
        "route_id": route_id,
        "vault_id": None,
        "order_amount_cents": amount,
        "forecast_basis": basis,
        "service_window_start": window_start,
        "service_window_end": window_end,
        "status": "SCHEDULED",
        "expected_vault_version": None,
    }
    store.stamp_new(order)
    store.replenishment_orders[order["id"]] = order
    return ok_object(store.clock, serialize.replenishment_order(order), 201)


@bp.route("/replenishment-orders/<oid>", methods=["GET"])
def get_order(oid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "VaultController", "FieldTech"})
    order = lookups.replenishment_order(store, oid)
    return ok_object(store.clock, serialize.replenishment_order(order))


@bp.route("/replenishment-orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "VaultController", "FieldTech"})
    limit, offset = validate.parse_pagination(request.args)
    atm_id = request.args.get("atm_id")
    route_id = request.args.get("route_id")
    vault_id = request.args.get("vault_id")
    items = store.sorted_values(store.replenishment_orders)
    if atm_id is not None:
        items = [o for o in items if o["atm_id"] == atm_id]
    if route_id is not None:
        items = [o for o in items if o["route_id"] == route_id]
    if vault_id is not None:
        items = [o for o in items if o.get("vault_id") == vault_id]
    page, total = validate.paginate(
        [serialize.replenishment_order(o) for o in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


@bp.route("/replenishment-orders/<oid>/dispatch", methods=["POST"])
def dispatch_order(oid):
    _, role = authenticate()
    authorize(role, {"VaultController"})
    order = lookups.replenishment_order(store, oid)
    body = validate.get_body()
    # OCC token is required on dispatch (PRD §2.8 "must carry").
    expected_version = validate.require_int(body, "expected_vault_version")
    # State guard (priority 6) BEFORE dispatch-specific checks.
    if order["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Order is not SCHEDULED.")
    atm = lookups.atm(store, order["atm_id"])
    route = lookups.route(store, order["route_id"])
    vault = lookups.vault(store, route["vault_id"])
    order = repl_svc.dispatch(store, order, atm, route, vault, expected_version)
    return ok_object(store.clock, serialize.replenishment_order(order))


@bp.route("/replenishment-orders/<oid>/confirm-load", methods=["POST"])
def confirm_load(oid):
    _, role = authenticate()
    authorize(role, {"FieldTech"})
    order = lookups.replenishment_order(store, oid)
    body = validate.get_body()
    allocations = body.get("cassette_allocations")
    # State guard.
    if order["status"] != "DISPATCHED":
        raise err("ERR_INVALID_STATE", "Order is not DISPATCHED.")
    atm = lookups.atm(store, order["atm_id"])
    # ERR_ATM_OUT_OF_SERVICE (priority 12).
    if atm["operational_status"] == "OUT_OF_SERVICE":
        raise err("ERR_ATM_OUT_OF_SERVICE", "ATM is out of service.")
    order = repl_svc.confirm_load(store, order, atm, allocations)
    return ok_object(store.clock, serialize.replenishment_order(order))


@bp.route("/replenishment-orders/<oid>/recall", methods=["POST"])
def recall_order(oid):
    _, role = authenticate()
    authorize(role, {"VaultController"})
    order = lookups.replenishment_order(store, oid)
    # Recall is only defined from SCHEDULED or DISPATCHED.
    if order["status"] not in ("SCHEDULED", "DISPATCHED"):
        raise err("ERR_INVALID_STATE", "Order cannot be recalled from its current state.")
    atm = store.atms.get(order["atm_id"])
    vault = store.vaults.get(order.get("vault_id")) if order.get("vault_id") else None
    order = repl_svc.recall(store, order, atm, vault)
    return ok_object(store.clock, serialize.replenishment_order(order))
