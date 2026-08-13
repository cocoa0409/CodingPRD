"""FactoryOrder endpoints (PRD §3.2)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store, stamp_new, touch, now_dt, clock_date
from errors import err_not_found, err_invalid, ApiError
from helpers import (body, req_str, req_enum, opt_str, req_int,
                     paginate, sort_created, apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import factory_order as ser
import services

bp = Blueprint("orders", __name__)

CHASSIS_MODELS = {"CASCADIA_126", "M2_106", "SD_114"}
ENGINE_OPTIONS = {"DD13", "DD15", "CUMMINS_X15"}
AXLE_CONFIGS = {"A4X2", "A6X4"}
HOLD_DAYS = 14


def _get_order(rid):
    o = store.factory_orders.get(rid)
    if o is None:
        raise err_not_found("FACTORY_ORDER")
    return o


def _parse_upfit_lines(data):
    raw = data.get("upfit_lines", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise err_invalid("Field upfit_lines must be an array")
    lines = []
    for item in raw:
        if not isinstance(item, dict):
            raise err_invalid("Each upfit line must be an object")
        code = req_enum(item, "component_code", services.UPFIT_CODES)
        price = req_int(item, "price_cents", minimum=0)
        lines.append({"component_code": code, "price_cents": price})
    return lines


def _check_slot_holdable(slot):
    """Temporal (17) before capacity (18)."""
    if services.month_is_closed(slot):
        raise ApiError("ERR_SLOT_MONTH_CLOSED", 409,
                       "Slot pool build month has passed")
    if services.slots_available(slot) < 1:
        raise ApiError("ERR_SLOT_POOL_EXHAUSTED", 409,
                       "Slot pool has no capacity remaining")


@bp.post("/dealership/factory-orders")
def create_order():
    caller(["SalesConsultant"])
    data = body()
    slot_id = req_str(data, "factory_build_slot_id")
    chassis = req_enum(data, "chassis_model", CHASSIS_MODELS)
    engine = req_enum(data, "engine_option", ENGINE_OPTIONS)
    axle = req_enum(data, "axle_config", AXLE_CONFIGS)
    account_id = opt_str(data, "customer_account_id")
    upfit_lines = _parse_upfit_lines(data)

    slot = store.factory_build_slots.get(slot_id)
    if slot is None:
        raise err_not_found("FACTORY_BUILD_SLOT")
    if account_id is not None and account_id not in store.customer_accounts:
        raise err_not_found("CUSTOMER_ACCOUNT")

    # Upfit compatibility (8) before slot temporal (17) / capacity (18).
    services.validate_upfit(slot["vocation_group"],
                            [l["component_code"] for l in upfit_lines])
    _check_slot_holdable(slot)

    order = {
        "customer_account_id": account_id,
        "factory_build_slot_id": slot["id"],
        "chassis_model": chassis,
        "engine_option": engine,
        "axle_config": axle,
        "vocation_group": slot["vocation_group"],
        "upfit_lines": upfit_lines,
        "_hold_expires_dt": now_dt() + timedelta(days=HOLD_DAYS),
        "provisional_total_cents": services.factory_order_price(
            account_id, chassis, engine, axle, slot["vocation_group"],
            upfit_lines),
        "committed_total_cents": None,
        "received_unit_id": None,
        "status": "SLOT_HELD",
    }
    stamp_new(order)
    store.factory_orders[order["id"]] = order
    slot["held_count"] += 1
    touch(slot)
    services.reeval_slot_posture(slot)
    return success(ser(order), status=201)


@bp.get("/dealership/factory-orders")
def list_orders():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.factory_orders.values()), [
        ("customer_account_id", request.args.get("customer_account_id")),
        ("factory_build_slot_id", request.args.get("factory_build_slot_id")),
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([ser(o) for o in page], meta)


@bp.get("/dealership/factory-orders/<rid>")
def get_order(rid):
    caller(ALL_ROLES)
    return success(ser(_get_order(rid)))


@bp.post("/dealership/factory-orders/<rid>/upfit-lines")
def add_upfit_line(rid):
    caller(["SalesConsultant"])
    data = body()
    code = req_enum(data, "component_code", services.UPFIT_CODES)
    price = req_int(data, "price_cents", minimum=0)
    order = _get_order(rid)
    # Upfit compatibility (8) is evaluated against the full line set, then the
    # specification freeze (10) — PRD §2.10 priority order.
    codes = [l["component_code"] for l in order["upfit_lines"]] + [code]
    services.validate_upfit(order["vocation_group"], codes)
    if order["status"] != "SLOT_HELD":
        raise ApiError("ERR_SPEC_FROZEN", 409,
                       "Upfit lines may be added only while the order is SLOT_HELD")
    order["upfit_lines"].append({"component_code": code, "price_cents": price})
    order["provisional_total_cents"] = services.factory_order_price(
        order["customer_account_id"], order["chassis_model"],
        order["engine_option"], order["axle_config"], order["vocation_group"],
        order["upfit_lines"])
    touch(order)
    return success(ser(order), status=201)


@bp.post("/dealership/factory-orders/<rid>/commit")
def commit_order(rid):
    caller(["SalesConsultant"])
    order = _get_order(rid)
    if order["status"] != "SLOT_HELD":
        raise ApiError("ERR_ORDER_STATE", 409,
                       "Only a SLOT_HELD order may be committed")
    if now_dt() >= order["_hold_expires_dt"]:
        raise ApiError("ERR_ORDER_STATE", 409,
                       "Hold has lapsed; wait for sweep expiry or re-hold")
    order["committed_total_cents"] = services.factory_order_price(
        order["customer_account_id"], order["chassis_model"],
        order["engine_option"], order["axle_config"], order["vocation_group"],
        order["upfit_lines"])
    order["status"] = "COMMITTED"
    slot = store.factory_build_slots[order["factory_build_slot_id"]]
    slot["held_count"] -= 1
    slot["committed_count"] += 1
    touch(slot)
    touch(order)
    return success(ser(order))


@bp.post("/dealership/factory-orders/<rid>/re-hold")
def rehold_order(rid):
    caller(["SalesConsultant"])
    data = body()
    slot_id = req_str(data, "factory_build_slot_id")
    order = _get_order(rid)
    slot = store.factory_build_slots.get(slot_id)
    if slot is None:
        raise err_not_found("FACTORY_BUILD_SLOT")
    if order["status"] != "EXPIRED":
        raise ApiError("ERR_ORDER_STATE", 409,
                       "Only an EXPIRED order may be re-held")
    _check_slot_holdable(slot)
    order["factory_build_slot_id"] = slot["id"]
    order["vocation_group"] = slot["vocation_group"]
    order["_hold_expires_dt"] = now_dt() + timedelta(days=HOLD_DAYS)
    order["status"] = "SLOT_HELD"
    slot["held_count"] += 1
    touch(slot)
    services.reeval_slot_posture(slot)
    touch(order)
    return success(ser(order))


@bp.post("/dealership/factory-orders/<rid>/cancel")
def cancel_order(rid):
    caller(["SalesConsultant"])
    order = _get_order(rid)
    if order["status"] not in ("SLOT_HELD", "COMMITTED"):
        raise ApiError("ERR_ORDER_STATE", 409,
                       "Only SLOT_HELD or COMMITTED orders may be cancelled")
    slot = store.factory_build_slots[order["factory_build_slot_id"]]
    if order["status"] == "SLOT_HELD":
        slot["held_count"] -= 1
    else:
        slot["committed_count"] -= 1
        if order["customer_account_id"] is not None:
            account = store.customer_accounts.get(order["customer_account_id"])
            if account is not None:
                fee = services.rhu(Decimal(order["committed_total_cents"])
                                   * Decimal("0.02"))
                services.adjust_open_ar(account, fee)
    touch(slot)
    services.reeval_slot_posture(slot)
    order["status"] = "CANCELLED"
    touch(order)
    return success(ser(order))


@bp.post("/dealership/factory-orders/<rid>/receive")
def receive_order(rid):
    caller(["SalesManager"])
    data = body()
    vin = req_str(data, "vin")
    apr_bp = None
    if "apr_bp" in data and data["apr_bp"] is not None:
        apr_bp = req_int(data, "apr_bp", minimum=0)
    order = _get_order(rid)
    # State (7) before uniqueness (9).
    if order["status"] != "SHIPPED":
        raise ApiError("ERR_ORDER_STATE", 409,
                       "Only a SHIPPED order may be received")
    for u in store.units.values():
        if u["vin"] == vin:
            raise ApiError("ERR_DUPLICATE_VIN", 409,
                           "A unit with this VIN already exists")

    unit = {
        "vin": vin,
        "unit_kind": "NEW",
        "factory_order_id": order["id"],
        "trade_appraisal_id": None,
        "status": "IN_STOCK",
        "invoice_cost_cents": order["committed_total_cents"],
        "stocking_date": clock_date().isoformat(),
        "floorplan_active": True,
        "apr_bp": apr_bp if apr_bp is not None else 690,
        "floorplan_balance_cents": 0,
        "last_accrual_date": None,
        "recondition_count": 0,
        "sold_price_cents": None,
        "_sold_at_dt": None,
        "wholesale_price_cents": None,
        "wholesale_loss_cents": None,
        "_sweep_bucket": "B0_90",
    }
    stamp_new(unit)
    store.units[unit["id"]] = unit
    services.post_fp_entry(unit, "ADVANCE", unit["invoice_cost_cents"])
    unit["last_accrual_date"] = unit["stocking_date"]
    order["status"] = "DELIVERED"
    order["received_unit_id"] = unit["id"]
    touch(order)
    return success(ser(order))
