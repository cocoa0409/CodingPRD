"""EquipmentDepot, EbtTerminal, TerminalDeployment and EquipmentOrder routes."""
from flask import Blueprint

import calc
import serial
import services
from core import (bad_request, db, ensure_object, fail, filter_str, get_body,
                  mark, now, ok, ok_list, opt_enum, ordered, paginate, req_dt,
                  req_enum, req_int, req_str, require_auth, resolve_body_ref,
                  resolve_path, stamp_new)
from guards import (ADMIN, ADMIN_ANALYST, OWNER_ADMIN, check_store_scope,
                    check_state_code, validate_order_lines)

bp = Blueprint("equipment", __name__)

TERMINAL_MODELS = ("EBT_ONLY_WIRELESS", "EBT_ONLY_DIAL", "COMMERCIAL_INTEGRATED")
CLOSE_REASON_CODES = ("AUTHORIZATION_LOST", "INVESTIGATION_FREEZE",
                      "RETAILER_REQUEST", "END_OF_TERM", "DAMAGED")
CANCEL_REASON_CODES = ("RETAILER_REQUEST", "AUTHORIZATION_LOST",
                       "DUPLICATE_ORDER")
TERMINAL_READ_ROLES = ("FnsAdmin", "FnsAnalyst", "RetailerOwner")
DEPLOYMENT_READ_ROLES = ("FnsAdmin", "FnsAnalyst", "RetailerOwner", "StoreClerk")
ORDER_READ_ROLES = ("FnsAdmin", "FnsAnalyst", "RetailerOwner")
UNAVAILABLE_TERMINAL_STATUSES = ("PENDING_RETURN", "RETIRED")


# --- depots ----------------------------------------------------------------
@bp.post("/equipment-depots")
def create_depot():
    require_auth(ADMIN)
    body = get_body()
    ensure_object(body)
    state_code = check_state_code(req_str(body, "state_code"))
    total = req_int(body, "total_units_owned", minimum=0)
    row = stamp_new({
        "state_code": state_code,
        "total_units_owned": total,
        "units_reserved": 0,
        "units_deployed": 0,
        "units_pending_return": 0,
        "units_retired": 0,
        "units_in_stock": total,
    })
    db.equipment_depots[row["id"]] = row
    return ok(serial.equipment_depot(row), 201)


@bp.get("/equipment-depots/<depot_id>")
def get_depot(depot_id):
    require_auth(ADMIN_ANALYST)
    row = resolve_path(db.equipment_depots, depot_id, "ERR_DEPOT_NOT_FOUND")
    return ok(serial.equipment_depot(row))


@bp.get("/equipment-depots")
def list_depots():
    require_auth(ADMIN_ANALYST)
    rows = ordered(list(db.equipment_depots.values()))
    state_code = filter_str("state_code")
    if state_code is not None:
        rows = [r for r in rows if r.get("state_code") == state_code]
    data, pagination = paginate(rows, serial.equipment_depot)
    return ok_list(data, pagination)


# --- terminals -------------------------------------------------------------
@bp.post("/ebt-terminals")
def create_terminal():
    require_auth(ADMIN)
    body = get_body()
    ensure_object(body)
    depot = resolve_body_ref(body, "depot_id", db.equipment_depots,
                            "ERR_DEPOT_NOT_FOUND")
    serial_number = req_str(body, "serial_number")
    model = req_enum(body, "model", TERMINAL_MODELS)
    if depot is None:
        req_str(body, "depot_id")
    for other in db.ebt_terminals.values():
        if other["serial_number"] == serial_number and \
                other["status"] != "RETIRED":
            fail("ERR_DUPLICATE_TERMINAL_SERIAL")
    row = stamp_new({
        "depot_id": depot["id"],
        "serial_number": serial_number,
        "model": model,
        "status": "IN_STOCK",
    })
    db.ebt_terminals[row["id"]] = row
    services.sync_depot(depot)
    services.commit()
    return ok(serial.ebt_terminal(row), 201)


@bp.get("/ebt-terminals/<terminal_id>")
def get_terminal(terminal_id):
    require_auth(TERMINAL_READ_ROLES)
    row = resolve_path(db.ebt_terminals, terminal_id, "ERR_TERMINAL_NOT_FOUND")
    return ok(serial.ebt_terminal(row))


@bp.get("/ebt-terminals")
def list_terminals():
    require_auth(TERMINAL_READ_ROLES)
    rows = ordered(list(db.ebt_terminals.values()))
    for name in ("depot_id", "status", "model", "serial_number"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.ebt_terminal)
    return ok_list(data, pagination)


# --- deployments -----------------------------------------------------------
@bp.post("/terminal-deployments")
def create_deployment():
    require_auth(ADMIN)
    body = get_body()
    ensure_object(body)
    store = resolve_body_ref(body, "store_id", db.stores, "ERR_STORE_NOT_FOUND")
    terminal = resolve_body_ref(body, "terminal_id", db.ebt_terminals,
                               "ERR_TERMINAL_NOT_FOUND")
    deploy_start = req_dt(body, "deploy_start")
    deploy_end = req_dt(body, "deploy_end")
    if store is None:
        req_str(body, "store_id")
    if terminal is None:
        req_str(body, "terminal_id")
    if deploy_end < deploy_start:
        bad_request("Field 'deploy_end' must be at or after 'deploy_start'.")
    if calc.deployment_conflicts(terminal["id"], deploy_start, deploy_end):
        fail("ERR_TERMINAL_ALREADY_COMMITTED")
    peak = calc.store_slot_peak(store["id"], deploy_start, deploy_end)
    if peak + 1 > store["max_terminal_slots"]:
        fail("ERR_STORE_TERMINAL_SLOTS_EXCEEDED")
    if terminal["status"] in UNAVAILABLE_TERMINAL_STATUSES:
        fail("ERR_DEPOT_STOCK_EXHAUSTED")
    row = stamp_new({
        "store_id": store["id"],
        "terminal_id": terminal["id"],
        "deploy_start": deploy_start,
        "deploy_end": deploy_end,
        "activated_at": None,
        "closed_at": None,
        "close_reason_code": None,
        "status": "RESERVED",
    })
    db.terminal_deployments[row["id"]] = row
    if terminal["status"] == "IN_STOCK":
        services.set_terminal_status(terminal, "RESERVED")
    else:
        services.sync_depot_of(terminal)
    services.commit()
    return ok(serial.terminal_deployment(row), 201)


@bp.get("/terminal-deployments/<deployment_id>")
def get_deployment(deployment_id):
    require_auth(DEPLOYMENT_READ_ROLES)
    row = resolve_path(db.terminal_deployments, deployment_id,
                       "ERR_DEPLOYMENT_NOT_FOUND")
    return ok(serial.terminal_deployment(row))


@bp.get("/terminal-deployments")
def list_deployments():
    require_auth(DEPLOYMENT_READ_ROLES)
    rows = ordered(list(db.terminal_deployments.values()))
    for name in ("store_id", "terminal_id", "status"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.terminal_deployment)
    return ok_list(data, pagination)


@bp.post("/terminal-deployments/<deployment_id>/activate")
def activate_deployment(deployment_id):
    require_auth(ADMIN)
    deployment = resolve_path(db.terminal_deployments, deployment_id,
                              "ERR_DEPLOYMENT_NOT_FOUND")
    if deployment["status"] != "RESERVED":
        fail("ERR_INVALID_STATE")
    store = db.stores.get(deployment["store_id"])
    if store is None or store["authorization_status"] != "AUTHORIZED":
        fail("ERR_STORE_NOT_AUTHORIZED")
    deployment["status"] = "ACTIVE"
    deployment["activated_at"] = now()
    mark(deployment)
    terminal = db.ebt_terminals.get(deployment["terminal_id"])
    if terminal is not None:
        services.resync_terminal(terminal)
    services.refresh_active_terminal_count(store)
    services.commit()
    return ok(serial.terminal_deployment(deployment))


def _close_reason(body):
    ensure_object(body)
    return opt_enum(body, "close_reason_code", CLOSE_REASON_CODES)


@bp.post("/terminal-deployments/<deployment_id>/recall")
def recall_deployment(deployment_id):
    require_auth(ADMIN)
    deployment = resolve_path(db.terminal_deployments, deployment_id,
                              "ERR_DEPLOYMENT_NOT_FOUND")
    reason = _close_reason(get_body())
    if deployment["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE")
    deployment["status"] = "RECALL_PENDING"
    if reason is not None:
        deployment["close_reason_code"] = reason
    mark(deployment)
    terminal = db.ebt_terminals.get(deployment["terminal_id"])
    if terminal is not None:
        services.resync_terminal(terminal)
    store = db.stores.get(deployment["store_id"])
    if store is not None:
        services.refresh_active_terminal_count(store)
    services.commit()
    return ok(serial.terminal_deployment(deployment))


@bp.post("/terminal-deployments/<deployment_id>/return")
def return_deployment(deployment_id):
    require_auth(ADMIN)
    deployment = resolve_path(db.terminal_deployments, deployment_id,
                              "ERR_DEPLOYMENT_NOT_FOUND")
    reason = _close_reason(get_body())
    if deployment["status"] not in ("ACTIVE", "RECALL_PENDING"):
        fail("ERR_INVALID_STATE")
    services.close_deployment(deployment, "RETURNED", reason)
    services.commit()
    return ok(serial.terminal_deployment(deployment))


@bp.post("/terminal-deployments/<deployment_id>/release")
def release_deployment(deployment_id):
    require_auth(ADMIN)
    deployment = resolve_path(db.terminal_deployments, deployment_id,
                              "ERR_DEPLOYMENT_NOT_FOUND")
    reason = _close_reason(get_body())
    if deployment["status"] != "RESERVED":
        fail("ERR_INVALID_STATE")
    services.close_deployment(deployment, "RELEASED", reason)
    services.commit()
    return ok(serial.terminal_deployment(deployment))


# --- equipment orders ------------------------------------------------------
@bp.post("/equipment-orders")
def create_order():
    require_auth(OWNER_ADMIN)
    body = get_body()
    ensure_object(body)
    store = resolve_body_ref(body, "store_id", db.stores, "ERR_STORE_NOT_FOUND")
    if store is not None:
        check_store_scope(store)
    lines = validate_order_lines(body, "lines")
    if store is None:
        req_str(body, "store_id")
    row = stamp_new({
        "store_id": store["id"],
        "lines": lines,
        "placed_at": None,
        "cancel_reason_code": None,
        "status": "DRAFT",
    })
    row.update(calc.equipment_totals(lines, store))
    db.equipment_orders[row["id"]] = row
    return ok(serial.equipment_order(row), 201)


@bp.get("/equipment-orders/<order_id>")
def get_order(order_id):
    require_auth(ORDER_READ_ROLES)
    row = resolve_path(db.equipment_orders, order_id,
                       "ERR_EQUIPMENT_ORDER_NOT_FOUND")
    return ok(serial.equipment_order(row))


@bp.get("/equipment-orders")
def list_orders():
    require_auth(ORDER_READ_ROLES)
    rows = ordered(list(db.equipment_orders.values()))
    for name in ("store_id", "status"):
        value = filter_str(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    data, pagination = paginate(rows, serial.equipment_order)
    return ok_list(data, pagination)


@bp.post("/equipment-orders/<order_id>/place")
def place_order(order_id):
    require_auth(OWNER_ADMIN)
    order = resolve_path(db.equipment_orders, order_id,
                         "ERR_EQUIPMENT_ORDER_NOT_FOUND")
    if order["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    store = db.stores.get(order["store_id"])
    if store is None or store["authorization_status"] != "AUTHORIZED":
        fail("ERR_STORE_NOT_AUTHORIZED")
    order["status"] = "PLACED"
    order["placed_at"] = now()
    mark(order)
    services.commit()
    return ok(serial.equipment_order(order))


@bp.post("/equipment-orders/<order_id>/fulfill")
def fulfill_order(order_id):
    require_auth(ADMIN)
    order = resolve_path(db.equipment_orders, order_id,
                         "ERR_EQUIPMENT_ORDER_NOT_FOUND")
    if order["status"] != "PLACED":
        fail("ERR_INVALID_STATE")
    order["status"] = "FULFILLED"
    mark(order)
    services.commit()
    return ok(serial.equipment_order(order))


@bp.post("/equipment-orders/<order_id>/cancel")
def cancel_order(order_id):
    require_auth(OWNER_ADMIN)
    order = resolve_path(db.equipment_orders, order_id,
                         "ERR_EQUIPMENT_ORDER_NOT_FOUND")
    body = get_body()
    ensure_object(body)
    reason = req_enum(body, "cancel_reason_code", CANCEL_REASON_CODES)
    if order["status"] not in ("DRAFT", "PLACED"):
        fail("ERR_INVALID_STATE")
    order["status"] = "CANCELLED"
    order["cancel_reason_code"] = reason
    mark(order)
    services.commit()
    return ok(serial.equipment_order(order))
