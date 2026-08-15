"""RouteOrder endpoints: manual create, list/get, confirm (dock buffer,
capacity, credit), cancel, deliver (price snapshot, invoice, crate DROP)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from clock import parse_iso, format_iso_ms
from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int, opt_iso_dt,
    base_fields, event_fields, paginate, err, touch, apply_changes, ceil_div,
    round_half_up_int, dec, parse_date,
)
from response import success_object, success_list
from errors import (
    ERR_INVALID_REQUEST, ERR_STORE_NOT_FOUND, ERR_TRIP_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND, ERR_ORDER_NOT_FOUND, ERR_OWNERSHIP_MISMATCH,
    ERR_STORE_NOT_ACTIVE, ERR_ROUTE_NOT_ACTIVE, ERR_TRIP_NOT_PLANNED,
    ERR_PRODUCT_DISCONTINUED, ERR_ORDER_NOT_CONFIRMABLE,
    ERR_ORDER_NOT_CANCELLABLE, ERR_ORDER_NOT_DELIVERABLE,
    ERR_TRIP_NOT_DEPARTED, ERR_DOCK_WINDOW_CONFLICT,
    ERR_TRIP_CAPACITY_EXCEEDED, ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_DELIVERY_QTY_EXCEEDS_ORDER, ERR_OUT_OF_CODE_DELIVERY,
    ERR_PRICING_PERIOD_NOT_FOUND,
)
from serializers import serialize_order
from services import (
    period_for_month, select_announcement, regulated_unit_price,
    invoice_amounts, refresh_trip_loaded_cases, refresh_store_open_ar,
    refresh_store_crates, order_case_count, order_delivered_case_count,
    DOCK_BUFFER_MINUTES,
)

bp = Blueprint("orders", __name__)


def get_order_or_404(order_id):
    o = DB.orders.get(order_id)
    if o is None:
        raise err(ERR_ORDER_NOT_FOUND, "RouteOrder id not found")
    return o


def owner_check_order(user_id, order):
    store = DB.stores.get(order["store_id"])
    route = DB.routes.get(store["route_id"]) if store else None
    if route is None or route["distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller does not own the order's route chain")


def _validate_line_shape(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        raise err(ERR_INVALID_REQUEST, "lines must be a non-empty array")
    for l in lines:
        if not isinstance(l, dict):
            raise err(ERR_INVALID_REQUEST, "each line must be an object")
        if "product_id" not in l or "quantity_units" not in l:
            raise err(ERR_INVALID_REQUEST, "each line requires product_id and quantity_units")
        if not isinstance(l["product_id"], str):
            raise err(ERR_INVALID_REQUEST, "line product_id must be a string")
    return lines


@bp.post("/dairy/orders")
def create_order():
    user_id, _role = require_role("DistributorOwner")
    body = get_json_body()
    check_unknown_fields(body, {"store_id", "trip_id", "lines",
                                "delivery_window_start", "delivery_window_end"})
    require_fields(body, ["store_id", "trip_id", "lines",
                          "delivery_window_start", "delivery_window_end"])
    store = DB.stores.get(body["store_id"])
    if store is None:
        raise err(ERR_STORE_NOT_FOUND, "Store id not found")
    route = DB.routes.get(store["route_id"])
    if route is None or route["distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller does not own the store's route")
    trip = DB.trips.get(body["trip_id"])
    if trip is None:
        raise err(ERR_TRIP_NOT_FOUND, "TruckTrip id not found")
    lines_in = _validate_line_shape(body["lines"])
    for l in lines_in:
        if DB.products.get(l["product_id"]) is None:
            raise err(ERR_PRODUCT_NOT_FOUND, "Product id not found")
    seen = set()
    for l in lines_in:
        qty = l["quantity_units"]
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) or (
                isinstance(qty, float) and not qty.is_integer()):
            raise err(ERR_INVALID_REQUEST, "line quantity_units must be an integer")
        if int(qty) <= 0:
            raise err(ERR_INVALID_REQUEST, "line quantity_units must be > 0")
        if l["product_id"] in seen:
            raise err(ERR_INVALID_REQUEST, "line product_id values must be distinct")
        seen.add(l["product_id"])
    win_start_raw = opt_iso_dt(body, "delivery_window_start")
    win_end_raw = opt_iso_dt(body, "delivery_window_end")
    win_start = parse_iso(win_start_raw)
    win_end = parse_iso(win_end_raw)
    if not (win_end > win_start):
        raise err(ERR_INVALID_REQUEST, "delivery_window_end must be strictly after delivery_window_start")
    if store["status"] != "ACTIVE":
        raise err(ERR_STORE_NOT_ACTIVE, "Store must be ACTIVE to accept orders")
    if trip["status"] != "PLANNED":
        raise err(ERR_TRIP_NOT_PLANNED, "Trip must be PLANNED to accept orders")
    if trip["route_id"] != store["route_id"]:
        raise err(ERR_INVALID_REQUEST, "Trip must serve the store's route")
    for l in lines_in:
        if DB.products[l["product_id"]]["status"] != "ACTIVE":
            raise err(ERR_PRODUCT_DISCONTINUED,
                      "DISCONTINUED products are rejected in manual order lines")
    lines = []
    total_cases = 0
    for l in lines_in:
        product = DB.products[l["product_id"]]
        cases = ceil_div(int(l["quantity_units"]), product["units_per_case"])
        lines.append({
            "product_id": l["product_id"],
            "quantity_units": int(l["quantity_units"]),
            "cases": cases,
        })
        total_cases += cases
    o = base_fields()
    o.update({
        "store_id": store["id"],
        "trip_id": trip["id"],
        "service_date": trip["service_date"],
        "source": "MANUAL",
        "lines": lines,
        "delivery_window_start": format_iso_ms(win_start),
        "delivery_window_end": format_iso_ms(win_end),
        "fulfillment_status": "PLANNED",
        "payment_status": "UNINVOICED",
        "subtotal_cents": 0,
    })
    DB.orders[o["id"]] = o
    # Cases are reserved at creation; capacity is enforced at confirm only.
    trip["loaded_cases"] += total_cases
    touch(trip)
    return success_object(serialize_order(o), status=201)


@bp.get("/dairy/orders/<orderId>")
def get_order(orderId):
    require_any()
    return success_object(serialize_order(get_order_or_404(orderId)))


@bp.get("/dairy/orders")
def list_orders():
    require_any()
    items = list(DB.orders.values())
    store_id = request.args.get("store_id")
    if store_id is not None:
        items = [o for o in items if o["store_id"] == store_id]
    trip_id = request.args.get("trip_id")
    if trip_id is not None:
        items = [o for o in items if o["trip_id"] == trip_id]
    fs = request.args.get("fulfillment_status")
    if fs is not None:
        items = [o for o in items if o["fulfillment_status"] == fs]
    items.sort(key=lambda o: o["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_order(o) for o in page], limit, offset, total)


def _estimated_subtotal(order):
    """Estimated subtotal at current prices: per-line rounding, pre-discount.
    Regulated lines without any announcement for the service month price at 0."""
    month = order["service_date"][:7]
    period = period_for_month(month)
    ann, _basis = select_announcement(period)
    total = 0
    for l in order["lines"]:
        product = DB.products[l["product_id"]]
        if product["regulated"]:
            if ann is None:
                price = dec(0)
            else:
                price = regulated_unit_price(product, ann)
        else:
            price = dec(product["list_price_cents"])
        total += round_half_up_int(dec(l["quantity_units"]) * price)
    return total


@bp.post("/dairy/orders/<orderId>/confirm")
def confirm_order(orderId):
    user_id, _role = require_role("DistributorOwner")
    o = get_order_or_404(orderId)
    owner_check_order(user_id, o)
    store = DB.stores[o["store_id"]]
    route = DB.routes[store["route_id"]]
    trip = DB.trips[o["trip_id"]]
    if o["fulfillment_status"] != "PLANNED":
        raise err(ERR_ORDER_NOT_CONFIRMABLE, "Order must be PLANNED to confirm")
    if store["status"] != "ACTIVE":
        raise err(ERR_STORE_NOT_ACTIVE, "Store must be ACTIVE to confirm")
    if route["status"] != "ACTIVE":
        raise err(ERR_ROUTE_NOT_ACTIVE, "The store's route must be ACTIVE to confirm")
    if trip["status"] != "PLANNED":
        raise err(ERR_TRIP_NOT_PLANNED, "Trip must be PLANNED to confirm")
    # Dock buffer: another CONFIRMED/DELIVERED order at same store+service_date
    # whose window is within 15 minutes on either side of this window.
    my_start = parse_iso(o["delivery_window_start"])
    my_end = parse_iso(o["delivery_window_end"])
    buffer = timedelta(minutes=DOCK_BUFFER_MINUTES)
    for other in DB.orders.values():
        if other["id"] == o["id"]:
            continue
        if other["store_id"] != o["store_id"]:
            continue
        if other["service_date"] != o["service_date"]:
            continue
        if other["fulfillment_status"] not in ("CONFIRMED", "DELIVERED"):
            continue
        o_start = parse_iso(other["delivery_window_start"])
        o_end = parse_iso(other["delivery_window_end"])
        # A gap of exactly the buffer (15 minutes) equals the buffer and is
        # allowed; strictly less than 15 minutes on either side conflicts.
        if o_start < my_end + buffer and my_start < o_end + buffer:
            raise err(ERR_DOCK_WINDOW_CONFLICT,
                      "Another confirmed/delivered order's window is within 15 minutes")
    # Capacity re-validation: loaded_cases already includes this reservation.
    if trip["loaded_cases"] > trip["case_capacity"]:
        raise err(ERR_TRIP_CAPACITY_EXCEEDED,
                  "Reserved case load exceeds the truck's case capacity")
    # Credit check (fiscal, last): strictly greater rejects; equality passes.
    estimated = _estimated_subtotal(o)
    if store["open_ar_cents"] + estimated > store["credit_limit_cents"]:
        raise err(ERR_CREDIT_LIMIT_EXCEEDED,
                  "Open AR plus estimated subtotal exceeds the store's credit limit")
    # Lines gain their case counts at confirm (SCAFFOLD §1.1 RouteOrder.lines).
    for l in o["lines"]:
        if "cases" not in l:
            product = DB.products[l["product_id"]]
            l["cases"] = ceil_div(l["quantity_units"], product["units_per_case"])
    o["fulfillment_status"] = "CONFIRMED"
    touch(o)
    return success_object(serialize_order(o))


@bp.post("/dairy/orders/<orderId>/cancel")
def cancel_order(orderId):
    user_id, _role = require_role("DistributorOwner")
    o = get_order_or_404(orderId)
    owner_check_order(user_id, o)
    if o["fulfillment_status"] not in ("PLANNED", "CONFIRMED"):
        raise err(ERR_ORDER_NOT_CANCELLABLE,
                  "Order must be PLANNED or CONFIRMED to cancel")
    o["fulfillment_status"] = "CANCELLED"
    touch(o)
    trip = DB.trips.get(o["trip_id"])
    if trip is not None:
        refresh_trip_loaded_cases(trip)  # releases the reservation
    return success_object(serialize_order(o))


@bp.post("/dairy/orders/<orderId>/deliver")
def deliver_order(orderId):
    user_id, _role = require_role("RouteDriver")
    o = get_order_or_404(orderId)
    trip = DB.trips[o["trip_id"]]
    if trip["driver_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller is not the trip's driver")
    body = get_json_body()
    check_unknown_fields(body, {"delivered_lines"})
    require_fields(body, ["delivered_lines"])
    delivered_in = body["delivered_lines"]
    if not isinstance(delivered_in, list):
        raise err(ERR_INVALID_REQUEST, "delivered_lines must be an array")
    for dl in delivered_in:
        if not isinstance(dl, dict):
            raise err(ERR_INVALID_REQUEST, "each delivered line must be an object")
        for f in ("product_id", "delivered_units", "scanned_code_date"):
            if f not in dl or dl[f] is None:
                raise err(ERR_INVALID_REQUEST, f"delivered line requires {f}")
        if not isinstance(dl["product_id"], str):
            raise err(ERR_INVALID_REQUEST, "delivered line product_id must be a string")
        du = dl["delivered_units"]
        if isinstance(du, bool) or not isinstance(du, (int, float)) or (
                isinstance(du, float) and not du.is_integer()):
            raise err(ERR_INVALID_REQUEST, "delivered_units must be an integer")
        if int(du) < 0:
            raise err(ERR_DELIVERY_QTY_EXCEEDS_ORDER,
                      "delivered_units must be >= 0")
        scd = dl["scanned_code_date"]
        if not isinstance(scd, str):
            raise err(ERR_INVALID_REQUEST, "scanned_code_date must be a date string")
        try:
            parse_date(scd)
        except Exception:
            raise err(ERR_INVALID_REQUEST, "scanned_code_date must be YYYY-MM-DD")
    if o["fulfillment_status"] != "CONFIRMED":
        raise err(ERR_ORDER_NOT_DELIVERABLE, "Order must be CONFIRMED to deliver")
    if trip["status"] != "DEPARTED":
        raise err(ERR_TRIP_NOT_DEPARTED, "Trip must be DEPARTED to deliver")
    # Transition preconditions in narrative order (PRD §2.5 / §3.4):
    # payload coverage and quantity first, then the code-date safety rule.
    order_line_ids = [l["product_id"] for l in o["lines"]]
    payload_ids = [dl["product_id"] for dl in delivered_in]
    if (len(payload_ids) != len(order_line_ids)
            or sorted(payload_ids) != sorted(order_line_ids)):
        raise err(ERR_DELIVERY_QTY_EXCEEDS_ORDER,
                  "delivered_lines must cover every ordered line exactly once")
    by_pid = {l["product_id"]: l for l in o["lines"]}
    for dl in delivered_in:
        if int(dl["delivered_units"]) > by_pid[dl["product_id"]]["quantity_units"]:
            raise err(ERR_DELIVERY_QTY_EXCEEDS_ORDER,
                      "delivered_units exceeds the ordered quantity")
    svc_date = parse_date(o["service_date"])
    for dl in delivered_in:
        if parse_date(dl["scanned_code_date"]) < svc_date:
            raise err(ERR_OUT_OF_CODE_DELIVERY,
                      "A delivered line's scanned_code_date is before the service date")
    # Pricing (point of use): announcement of the invoice month.
    month = o["service_date"][:7]
    period = period_for_month(month)
    ann, basis = select_announcement(period)
    needs_pricing = any(
        DB.products[l["product_id"]]["regulated"] for l in o["lines"]
    )
    if needs_pricing and ann is None:
        raise err(ERR_PRICING_PERIOD_NOT_FOUND,
                  "No announcement exists for the delivery's month")
    if basis is None:
        basis = "PROVISIONAL"

    # --- side effects (atomic: all preconditions passed) ---
    subtotal = 0
    for dl in delivered_in:
        line = by_pid[dl["product_id"]]
        product = DB.products[line["product_id"]]
        if product["regulated"]:
            price = regulated_unit_price(product, ann)
        else:
            price = dec(product["list_price_cents"])
        line["delivered_units"] = int(dl["delivered_units"])
        line["scanned_code_date"] = dl["scanned_code_date"]
        line["unit_price_cents"] = float(price)
        line["line_amount_cents"] = round_half_up_int(
            dec(line["delivered_units"]) * price)
        line["cold_chain_flag"] = False
        subtotal += line["line_amount_cents"]
    subtotal, discount, total = invoice_amounts(subtotal)
    o["fulfillment_status"] = "DELIVERED"
    o["subtotal_cents"] = subtotal
    o["payment_status"] = "INVOICED"
    touch(o)

    ordered_cases = order_case_count(o)
    delivered_cases = order_delivered_case_count(o)
    trip["loaded_cases"] -= ordered_cases
    trip["delivered_cases"] += delivered_cases
    touch(trip)

    inv = base_fields()
    inv.update({
        "order_id": o["id"],
        "store_id": o["store_id"],
        "invoice_month": month,
        "pricing_basis": basis,
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "total_cents": total,
        "credits_applied_cents": 0,
        "payments_applied_cents": 0,
        "amount_due_cents": total,
        "true_up_delta_cents": 0,
        "status": "OPEN",
    })
    DB.invoices[inv["id"]] = inv
    if inv["amount_due_cents"] == 0:
        inv["status"] = "SETTLED"
        apply_changes(o, {"payment_status": "PAID"})

    # Crate DROP (system-created) + deposit liability recompute.
    store = DB.stores[o["store_id"]]
    drop = event_fields()
    drop.update({
        "store_id": store["id"],
        "kind": "DROP",
        "crate_count": delivered_cases,
        "service_date": today_str(),
        "note": None,
    })
    DB.crate_transactions[drop["id"]] = drop
    refresh_store_crates(store)
    touch(store)
    refresh_store_open_ar(store["id"])
    return success_object(serialize_order(o))


def today_str():
    from clock import today_date
    return today_date().strftime("%Y-%m-%d")
