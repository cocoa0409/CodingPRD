"""Part / PartsSale / PartsSaleLine endpoints (PRD §3.9)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store, stamp_new, touch, now_dt
from errors import err_not_found, err_invalid, ApiError
from helpers import (body, req_str, req_int, opt_int, opt_bool, paginate,
                     sort_created, apply_filters)
from middleware import caller, ALL_ROLES
from response import success, success_list
from serializers import (part as part_ser, parts_sale as sale_ser,
                         parts_sale_line as line_ser)
import services

bp = Blueprint("parts", __name__)

RESTOCK_FEE_RATE = Decimal("0.15")
RESTOCK_FREE_DAYS = 30


# ---------- catalog ----------

@bp.post("/dealership/parts")
def create_part():
    caller(["PartsCounterRep"])
    data = body()
    sku = req_str(data, "sku")
    name = req_str(data, "part_name")
    list_price = req_int(data, "list_price_cents", minimum=1)
    cost = req_int(data, "cost_cents", minimum=0)
    on_hand = opt_int(data, "on_hand", 0, minimum=0)
    has_core = opt_bool(data, "has_core_charge", False)
    core_charge = opt_int(data, "core_charge_cents", 0, minimum=0)
    for p in store.parts.values():
        if p["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU", 409,
                           "A part with this SKU already exists")
    part = {
        "sku": sku,
        "part_name": name,
        "list_price_cents": list_price,
        "cost_cents": cost,
        "on_hand": on_hand,
        "has_core_charge": has_core,
        "core_charge_cents": core_charge,
        "status": "ACTIVE",
    }
    stamp_new(part)
    store.parts[part["id"]] = part
    return success(part_ser(part), status=201)


@bp.get("/dealership/parts")
def list_parts():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.parts.values()), [
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([part_ser(p) for p in page], meta)


@bp.get("/dealership/parts/<rid>")
def get_part(rid):
    caller(ALL_ROLES)
    part = store.parts.get(rid)
    if part is None:
        raise err_not_found("PART")
    return success(part_ser(part))


@bp.post("/dealership/parts/<rid>/discontinue")
def discontinue_part(rid):
    caller(["PartsCounterRep"])
    part = store.parts.get(rid)
    if part is None:
        raise err_not_found("PART")
    part["status"] = "DISCONTINUED"
    touch(part)
    return success(part_ser(part))


# ---------- counter sales ----------

@bp.post("/dealership/parts-sales")
def create_sale():
    caller(["PartsCounterRep"])
    data = body()
    account_id = req_str(data, "customer_account_id")
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise err_invalid("Field lines must be a non-empty array")
    parsed = []
    for item in raw_lines:
        if not isinstance(item, dict):
            raise err_invalid("Each sale line must be an object")
        pid = req_str(item, "part_id")
        qty = req_int(item, "quantity", minimum=1)
        parsed.append((pid, qty))

    account = store.customer_accounts.get(account_id)
    if account is None:
        raise err_not_found("CUSTOMER_ACCOUNT")
    parts = []
    for pid, qty in parsed:
        p = store.parts.get(pid)
        if p is None:
            raise err_not_found("PART")
        parts.append((p, qty))

    # Stock / active checks (14) across ALL lines before ANY decrement.
    for p, qty in parts:
        if p["on_hand"] < qty:
            raise ApiError("ERR_INSUFFICIENT_STOCK", 409,
                           "Insufficient part stock")
        if p["status"] != "ACTIVE":
            raise ApiError("ERR_PART_DISCONTINUED", 409,
                           "Part is discontinued")

    tier = account["fleet_tier"]
    subtotal = 0
    core_total = 0
    line_records = []
    for p, qty in parts:
        unit_net = services.parts_line_net_price(p["list_price_cents"], tier, qty)
        line_total = unit_net * qty
        subtotal += line_total
        if p["has_core_charge"]:
            core_total += p["core_charge_cents"] * qty
        line_records.append((p, qty, unit_net, line_total))

    sale = {
        "customer_account_id": account_id,
        "lines": [{"part_id": p["id"], "quantity": qty} for p, qty in parts],
        "subtotal_cents": subtotal,
        "core_total_cents": core_total,
        "total_cents": subtotal + core_total,
        "_sold_at_dt": now_dt(),
        "status": "INVOICED",
    }
    stamp_new(sale)
    store.parts_sales[sale["id"]] = sale

    for p, qty, unit_net, line_total in line_records:
        line = {
            "parts_sale_id": sale["id"],
            "part_id": p["id"],
            "quantity": qty,
            "unit_net_price_cents": unit_net,
            "line_total_cents": line_total,
            "returned_quantity": 0,
            "return_credit_cents": 0,
        }
        stamp_new(line)
        store.parts_sale_lines[line["id"]] = line
        p["on_hand"] -= qty
        touch(p)

    if account["account_type"] == "FLEET":
        services.adjust_open_ar(account, sale["total_cents"])
    return success(sale_ser(sale), status=201)


@bp.get("/dealership/parts-sales")
def list_sales():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.parts_sales.values()), [
        ("customer_account_id", request.args.get("customer_account_id")),
        ("status", request.args.get("status")),
    ])
    page, meta = paginate(items)
    return success_list([sale_ser(s) for s in page], meta)


@bp.get("/dealership/parts-sales/<rid>")
def get_sale(rid):
    caller(ALL_ROLES)
    sale = store.parts_sales.get(rid)
    if sale is None:
        raise err_not_found("PARTS_SALE")
    return success(sale_ser(sale))


@bp.get("/dealership/parts-sale-lines")
def list_sale_lines():
    caller(ALL_ROLES)
    items = apply_filters(sort_created(store.parts_sale_lines.values()), [
        ("parts_sale_id", request.args.get("parts_sale_id")),
        ("part_id", request.args.get("part_id")),
    ])
    page, meta = paginate(items)
    return success_list([line_ser(l) for l in page], meta)


@bp.get("/dealership/parts-sale-lines/<rid>")
def get_sale_line(rid):
    caller(ALL_ROLES)
    line = store.parts_sale_lines.get(rid)
    if line is None:
        raise err_not_found("PARTS_SALE_LINE")
    return success(line_ser(line))


@bp.post("/dealership/parts-sale-lines/<rid>/return")
def return_sale_line(rid):
    caller(["PartsCounterRep"])
    data = body()
    quantity = req_int(data, "quantity", minimum=1)
    line = store.parts_sale_lines.get(rid)
    if line is None:
        raise err_not_found("PARTS_SALE_LINE")
    sale = store.parts_sales.get(line["parts_sale_id"])
    if sale is None:
        raise err_not_found("PARTS_SALE")
    if sale["status"] not in ("INVOICED", "PARTIALLY_RETURNED"):
        raise err_invalid("Sale is fully returned")
    if line["returned_quantity"] + quantity > line["quantity"]:
        raise ApiError("ERR_RETURN_EXCEEDS_SOLD", 422,
                       "Return quantity exceeds sold-minus-returned")

    line["returned_quantity"] += quantity
    part = store.parts.get(line["part_id"])
    if part is not None:
        part["on_hand"] += quantity
        touch(part)

    gross = services.rhu(services.D(line["unit_net_price_cents"])
                         * services.D(quantity))
    fee = 0
    if now_dt() > sale["_sold_at_dt"] + timedelta(days=RESTOCK_FREE_DAYS):
        fee = services.rhu(RESTOCK_FEE_RATE * services.D(gross))
    credit = gross - fee
    line["return_credit_cents"] += credit
    touch(line)

    account = store.customer_accounts.get(sale["customer_account_id"])
    if account is not None and account["account_type"] == "FLEET":
        new_ar = max(0, account["open_ar_cents"] - credit)
        delta = new_ar - account["open_ar_cents"]
        if delta != 0:
            account["open_ar_cents"] = new_ar
            services.reeval_credit_posture(account)
            touch(account)

    sale_lines = [l for l in store.parts_sale_lines.values()
                  if l["parts_sale_id"] == sale["id"]]
    if all(l["returned_quantity"] == l["quantity"] for l in sale_lines):
        sale["status"] = "FULLY_RETURNED"
    else:
        sale["status"] = "PARTIALLY_RETURNED"
    touch(sale)
    return success(line_ser(line))
