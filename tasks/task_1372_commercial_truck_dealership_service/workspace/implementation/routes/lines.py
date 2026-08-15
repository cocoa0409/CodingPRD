"""RepairOrderLine endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import store, stamp_new, touch
from errors import err_not_found, err_invalid, ApiError
from helpers import (body, req_str, req_enum, opt_str, req_int, req_number,
                     opt_bool, paginate, sort_created, apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import repair_order_line as ser
import services

bp = Blueprint("lines", __name__)

LINE_TYPES = {"LABOR", "PART"}


@bp.post("/dealership/repair-order-lines")
def create_line():
    caller(["ServiceAdvisor"])
    data = body()
    ro_id = req_str(data, "repair_order_id")
    line_type = req_enum(data, "line_type", LINE_TYPES)
    description = opt_str(data, "description")
    warranty_eligible = opt_bool(data, "warranty_eligible", False)

    hours = None
    quantity = None
    part_id = None
    if line_type == "LABOR":
        hours = req_number(data, "hours")
        if hours <= 0:
            raise err_invalid("hours must be greater than zero")
    else:
        part_id = req_str(data, "part_id")
        quantity = req_int(data, "quantity", minimum=1)

    ro = store.repair_orders.get(ro_id)
    if ro is None:
        raise err_not_found("REPAIR_ORDER")
    part = None
    if line_type == "PART":
        part = store.parts.get(part_id)
        if part is None:
            raise err_not_found("PART")

    # State (7) before stock / active checks (14).
    if ro["auth_status"] not in ("DRAFT", "DECLINED") or \
            ro["work_status"] not in ("OPEN", "SCHEDULED"):
        raise ApiError("ERR_RO_STATE", 409,
                       "Lines may be added only while the estimate is in "
                       "DRAFT/DECLINED and work is OPEN/SCHEDULED")

    if line_type == "LABOR":
        unit_price = ro["labor_rate_cents"]
        line_total = services.rhu(services.D(hours) * services.D(unit_price))
    else:
        if part["on_hand"] < quantity:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409,
                           "Insufficient part stock")
        if part["status"] != "ACTIVE":
            raise ApiError("ERR_PART_DISCONTINUED", 409,
                           "Part is discontinued")
        unit_price = part["list_price_cents"]
        line_total = quantity * unit_price

    line = {
        "repair_order_id": ro["id"],
        "line_type": line_type,
        "part_id": part_id,
        "description": description,
        "hours": hours,
        "quantity": quantity,
        "unit_price_cents": unit_price,
        "line_total_cents": line_total,
        "warranty_eligible": warranty_eligible,
    }
    stamp_new(line)
    store.repair_order_lines[line["id"]] = line
    if part is not None:
        part["on_hand"] -= quantity
        touch(part)
    services.recompute_ro_sums(ro)
    touch(ro)
    return success(ser(line), status=201)


@bp.get("/dealership/repair-order-lines")
def list_lines():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.repair_order_lines.values()), [
        ("repair_order_id", request.args.get("repair_order_id")),
        ("part_id", request.args.get("part_id")),
    ])
    page, meta = paginate(items)
    return success_list([ser(l) for l in page], meta)


@bp.get("/dealership/repair-order-lines/<rid>")
def get_line(rid):
    caller(ALL_ROLES)
    line = store.repair_order_lines.get(rid)
    if line is None:
        raise err_not_found("REPAIR_ORDER_LINE")
    return success(ser(line))
