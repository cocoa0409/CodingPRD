"""Order routes — the central workflow (PRD §3.2, §3.6, §3.7, §3.8).

Confirm is the pivot transaction: lock line prices, compute turnaround dates,
strike totals, reserve daily capacity — all atomic (check every precondition
before committing any change).
"""

from flask import Blueprint, request, g

import db
import errors
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services import serialize
from services import pricing
from services.ownership import require_order_owner
from services.common import (
    get_body, require_fields, require_int, require_str, lookup, list_collection,
)

bp = Blueprint("orders", __name__)


# ---------------------------------------------------------------------------
# Create / read / list.
# ---------------------------------------------------------------------------
@bp.post("/orders")
@require_roles("ShopStaff", "Customer")
def create_order():
    body = get_body()
    require_fields(body, "shop_id", "customer_id")
    shop_id = require_str(body, "shop_id")
    lookup(db.shops, shop_id)
    customer_id = require_str(body, "customer_id")
    lookup(db.customers, customer_id)

    # A customer may only open an order for themselves.
    if g.user_role == "Customer" and customer_id != g.user_id:
        raise err(errors.ERR_NOT_ORDER_OWNER,
                  "Customer may only create orders for themselves")

    rec = _new_order(shop_id, customer_id, reordered_from=None)
    db.orders[rec["id"]] = rec
    return object_response(serialize.order(rec), 201)


def _new_order(shop_id, customer_id, reordered_from):
    rec = {
        "shop_id": shop_id,
        "customer_id": customer_id,
        "reordered_from_order_id": reordered_from,
        "production_status": "DRAFT",
        "payment_status": "UNPAID",
        "subtotal_cents": 0,
        "loyalty_discount_cents": 0,
        "rush_fee_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
        "promised_ready_date": None,
    }
    db.stamp_new(rec)
    return rec


@bp.get("/orders")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_orders():
    customer_id = request.args.get("customer_id")
    shop_id = request.args.get("shop_id")
    reordered_from = request.args.get("reordered_from_order_id")

    def pred(r):
        if customer_id is not None and r["customer_id"] != customer_id:
            return False
        if shop_id is not None and r["shop_id"] != shop_id:
            return False
        if reordered_from is not None and r["reordered_from_order_id"] != reordered_from:
            return False
        return True

    items, limit, offset, total = list_collection(db.orders, pred)
    return array_response([serialize.order(r) for r in items], limit, offset, total)


@bp.get("/orders/<order_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_order(order_id):
    rec = lookup(db.orders, order_id)
    return object_response(serialize.order(rec), 200)


# ---------------------------------------------------------------------------
# Reorder (PRD §3.8).
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/reorder")
@require_roles("ShopStaff", "Customer")
def reorder(order_id):
    source = lookup(db.orders, order_id)
    require_order_owner(source)

    body = get_body()
    require_fields(body, "expected_order_version")
    expected = require_int(body, "expected_order_version")
    # Reorder does not list an OCC error in §2.9 (only confirm/cancel guard with
    # ERR_STALE_ORDER_VERSION); it still increments the source version. The
    # expected_order_version is accepted as input per the endpoint contract.

    new_order = _new_order(source["shop_id"], source["customer_id"],
                           reordered_from=source["id"])
    db.orders[new_order["id"]] = new_order

    # Clone each source line as a fresh OPEN line.
    src_lines = [l for l in db.order_lines.values() if l["order_id"] == source["id"]]
    src_lines.sort(key=lambda l: l["_seq"])
    for sl in src_lines:
        product = db.products.get(sl["product_id"])
        codes = list(sl["finishing_codes"])
        if product is not None:
            estimate = pricing.compute_line_price(product, sl["quantity"], codes)
            units = pricing.production_units(product, sl["quantity"])
        else:
            estimate = 0
            units = 0
        line = {
            "order_id": new_order["id"],
            "product_id": sl["product_id"],
            "quantity": sl["quantity"],
            "finishing_codes": codes,
            "service_level": sl["service_level"],
            "status": "OPEN",
            "production_units": units,
            "estimate_line_cents": estimate,
            "final_line_cents": None,
            "rush_surcharge_cents": 0,
            "promised_ready_date": None,
        }
        db.stamp_new(line)
        db.order_lines[line["id"]] = line

    # The act of reordering increments the source order's version.
    db.touch(source)

    return object_response(serialize.order(new_order), 201)


# ---------------------------------------------------------------------------
# Confirm (PRD §3.6) — the pivot transaction.
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/confirm")
@require_roles("Customer")
def confirm(order_id):
    order = lookup(db.orders, order_id)
    require_order_owner(order)

    # State (5): production_status must be DRAFT.
    if order["production_status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "Order is not in DRAFT")

    # OCC (6): expected_order_version must match Order.version, before any commit.
    body = get_body()
    require_fields(body, "expected_order_version")
    expected = require_int(body, "expected_order_version")
    if expected != order["version"]:
        raise err(errors.ERR_STALE_ORDER_VERSION,
                  "expected_order_version does not match current version")

    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: l["_seq"])

    # Business: line-lockable (9). Order must have >= 1 line and every line
    # price-lockable (proof-approved if requires_proof else preflight-ok) AND a
    # CONFIRMED press booking for every requires_press line.
    if not lines:
        raise err(errors.ERR_LINE_NOT_LOCKABLE, "Order has no lines to lock")
    for line in lines:
        product = db.products[line["product_id"]]
        if product["requires_proof"]:
            if line["status"] != "PROOF_APPROVED":
                raise err(errors.ERR_LINE_NOT_LOCKABLE,
                          "Line %s is not PROOF_APPROVED" % line["id"])
        else:
            if line["status"] != "PREFLIGHT_OK":
                raise err(errors.ERR_LINE_NOT_LOCKABLE,
                          "Line %s is not PREFLIGHT_OK" % line["id"])
        if product["requires_press"]:
            if not _has_confirmed_press_booking(line["id"]):
                raise err(errors.ERR_LINE_NOT_LOCKABLE,
                          "Line %s lacks a confirmed press booking" % line["id"])

    # Business: fulfillment-required (10).
    fulfillment = _order_fulfillment(order_id)
    if fulfillment is None:
        raise err(errors.ERR_FULFILLMENT_REQUIRED,
                  "A fulfillment must exist before confirm")

    # ----- All non-capacity preconditions hold. Compute turnaround + prices. -----
    shop = db.shops[order["shop_id"]]
    current = db.current_utc()

    # Compute per-line promised dates (needed for capacity dates) without committing.
    plan = []  # (line, final_line_cents, rush_surcharge_cents, units, ready_date)
    for line in lines:
        product = db.products[line["product_id"]]
        final_cents = pricing.compute_line_price(
            product, line["quantity"], line["finishing_codes"])
        rush = pricing.compute_rush_surcharge(final_cents, line["service_level"], shop)
        units = pricing.production_units(product, line["quantity"])
        ready = pricing.line_turnaround_date(current, line["service_level"], shop)
        plan.append((line, final_cents, rush, units, ready))

    # Business: capacity (14) — check ALL lines before committing any reservation.
    # Running per-date load starts from existing HELD reservations, then accrues
    # this confirm's lines so multiple same-date lines are counted together.
    date_load = {}
    for line, _final, _rush, units, ready in plan:
        if ready not in date_load:
            date_load[ready] = _held_units_on_date(order["shop_id"], ready)
        if date_load[ready] + units > shop["daily_unit_capacity"]:
            raise err(errors.ERR_CAPACITY_EXCEEDED,
                      "Production date %s would exceed daily capacity" % ready)
        date_load[ready] += units

    # ----- Commit: every precondition held. -----
    latest_date = None
    for line, final_cents, rush, units, ready in plan:
        line["status"] = "PRICE_LOCKED"
        line["final_line_cents"] = final_cents
        line["rush_surcharge_cents"] = rush
        line["production_units"] = units
        line["promised_ready_date"] = ready
        db.touch(line)
        if latest_date is None or ready > latest_date:
            latest_date = ready

    # Totals in pinned order (PRD §3.6). subtotal = sum of locked final_line_cents
    # (each already whole-cent, so the sum is exact and not re-rounded).
    subtotal = sum(line["final_line_cents"] for line in lines)
    loyalty_discount = pricing.loyalty_discount_cents(subtotal, db.customers[order["customer_id"]]["loyalty_tier"])
    rush_fee = sum(line["rush_surcharge_cents"] for line in lines)
    taxable_base = subtotal - loyalty_discount
    tax = pricing.bps_apply(taxable_base, shop["tax_rate_bps"])
    ship_fee = fulfillment["ship_fee_cents"]
    total = taxable_base + rush_fee + tax + ship_fee

    order["subtotal_cents"] = subtotal
    order["loyalty_discount_cents"] = loyalty_discount
    order["rush_fee_cents"] = rush_fee
    order["tax_cents"] = tax
    order["total_cents"] = total
    order["promised_ready_date"] = latest_date

    # Reserve daily capacity per line (HELD).
    for line, _final, _rush, units, ready in plan:
        res = {
            "shop_id": order["shop_id"],
            "order_line_id": line["id"],
            "production_date": ready,
            "units": units,
            "status": "HELD",
        }
        db.stamp_new(res)
        db.capacity_reservations[res["id"]] = res

    order["production_status"] = "CONFIRMED"
    db.touch(order)  # increments version

    return object_response(serialize.order(order), 200)


# ---------------------------------------------------------------------------
# Cancel (PRD §3.8) — cascade releases.
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/cancel")
@require_roles("Customer")
def cancel(order_id):
    order = lookup(db.orders, order_id)
    require_order_owner(order)

    # State (5): production_status must be DRAFT or CONFIRMED.
    if order["production_status"] not in ("DRAFT", "CONFIRMED"):
        raise err(errors.ERR_INVALID_STATE,
                  "Only a DRAFT or CONFIRMED order may be cancelled")

    # OCC (6).
    body = get_body()
    require_fields(body, "expected_order_version")
    expected = require_int(body, "expected_order_version")
    if expected != order["version"]:
        raise err(errors.ERR_STALE_ORDER_VERSION,
                  "expected_order_version does not match current version")

    order["production_status"] = "CANCELLED"

    line_ids = {l["id"] for l in db.order_lines.values() if l["order_id"] == order_id}
    # Cascade: every HELD CapacityReservation for the order's lines -> RELEASED.
    for res in db.capacity_reservations.values():
        if res["order_line_id"] in line_ids and res["status"] == "HELD":
            res["status"] = "RELEASED"
            db.touch(res)
    # Cascade: every CONFIRMED PressBooking for the order's lines -> RELEASED.
    for b in db.press_bookings.values():
        if b["order_line_id"] in line_ids and b["status"] == "CONFIRMED":
            b["status"] = "RELEASED"
            db.touch(b)

    db.touch(order)  # increments version
    return object_response(serialize.order(order), 200)


# ---------------------------------------------------------------------------
# Start production (PRD §3.7).
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/start-production")
@require_roles("ProductionOperator")
def start_production(order_id):
    order = lookup(db.orders, order_id)
    if order["production_status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Order must be CONFIRMED")
    if order["payment_status"] not in ("INVOICED", "PAID"):
        raise err(errors.ERR_INVALID_STATE,
                  "Order must be INVOICED or PAID to start production")
    order["production_status"] = "IN_PRODUCTION"
    db.touch(order)
    return object_response(serialize.order(order), 200)


# ---------------------------------------------------------------------------
# Invoice (PRD §3.7).
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/invoice")
@require_roles("ShopStaff")
def invoice(order_id):
    order = lookup(db.orders, order_id)
    if order["payment_status"] != "UNPAID":
        raise err(errors.ERR_INVALID_STATE, "Order payment_status must be UNPAID")
    if order["production_status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        raise err(errors.ERR_INVALID_STATE,
                  "Order must be CONFIRMED or IN_PRODUCTION to invoice")
    if order["total_cents"] <= 0:
        raise err(errors.ERR_INVALID_STATE, "Order total must be > 0 to invoice")
    order["payment_status"] = "INVOICED"
    db.touch(order)
    return object_response(serialize.order(order), 200)


# ---------------------------------------------------------------------------
# Pay (PRD §3.7).
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/pay")
@require_roles("Customer")
def pay(order_id):
    order = lookup(db.orders, order_id)
    require_order_owner(order)
    if order["payment_status"] != "INVOICED":
        raise err(errors.ERR_INVALID_STATE, "Order must be INVOICED to pay")

    body = get_body()
    require_fields(body, "amount_cents")
    amount = require_int(body, "amount_cents")
    if amount != order["total_cents"]:
        raise err(errors.ERR_PAYMENT_AMOUNT_MISMATCH,
                  "amount_cents must equal Order.total_cents")

    order["payment_status"] = "PAID"
    db.touch(order)

    cust = db.customers.get(order["customer_id"])
    if cust is not None:
        cust["lifetime_paid_cents"] += order["total_cents"]
        db.touch(cust)

    return object_response(serialize.order(order), 200)


# ---------------------------------------------------------------------------
# Refund (PRD §3.8).
# ---------------------------------------------------------------------------
@bp.post("/orders/<order_id>/refund")
@require_roles("ShopStaff")
def refund(order_id):
    order = lookup(db.orders, order_id)
    if order["payment_status"] != "PAID" or order["production_status"] != "CANCELLED":
        raise err(errors.ERR_INVALID_STATE,
                  "Refund requires payment_status PAID and production_status CANCELLED")

    order["payment_status"] = "REFUNDED"
    db.touch(order)

    cust = db.customers.get(order["customer_id"])
    if cust is not None:
        cust["lifetime_paid_cents"] -= order["total_cents"]
        db.touch(cust)

    return object_response(serialize.order(order), 200)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------
def _has_confirmed_press_booking(order_line_id):
    return any(b["order_line_id"] == order_line_id and b["status"] == "CONFIRMED"
               for b in db.press_bookings.values())


def _order_fulfillment(order_id):
    matches = [f for f in db.fulfillments.values() if f["order_id"] == order_id]
    matches.sort(key=lambda f: f["_seq"])
    return matches[0] if matches else None


def _held_units_on_date(shop_id, production_date):
    return sum(r["units"] for r in db.capacity_reservations.values()
               if r["shop_id"] == shop_id
               and r["production_date"] == production_date
               and r["status"] == "HELD")
