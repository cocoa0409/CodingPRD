"""Order endpoints and payment axis (PRD §3.5–§3.8)."""

import math
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import errors
from clock import clock
from db import db, new_id
from middleware import require_roles
from response import success_empty, success_list, success_object
from services.domain import (
    check_area_restrictions,
    credit_wallet,
    day_before_cutoff,
    debit_wallet,
    recompute_loyalty_tier,
    serialize_invoice,
    serialize_order,
    serialize_order_line,
    serialize_payment_event,
)
from services.pricing import (
    CORD_EQUIVALENT_PER_UNIT,
    compute_cancellation_fee,
    compute_reading_pass,
    compute_unit_price_cents,
    invoice_due_date,
    line_cord_equivalent,
    next_invoice_number,
    recompute_order_pricing,
    season_window_contains,
)
from util import (
    dec,
    get_json_body,
    now_iso,
    paginate,
    parse_pagination,
    require_field,
    require_int,
    require_number,
    require_str,
    touch,
)

bp = Blueprint("orders", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_order_or_404(oid):
    o = db.orders.get(oid)
    if not o:
        raise errors.not_found(f"Order {oid} not found")
    return o


def _get_line_or_404(lid):
    l = db.order_lines.get(lid)
    if not l:
        raise errors.not_found(f"OrderLine {lid} not found")
    return l


def _check_customer_owns_order(auth, order):
    if auth.is_customer() and auth.user_id != order["customer_id"]:
        raise errors.unauthorized("Customers may only access their own orders")


def _validate_quantity(product_kind, quantity):
    """Per-kind granularity (PRD §3.5, validation 11)."""
    q = dec(quantity)
    if q <= 0:
        raise errors.invalid_quantity("quantity must be positive")
    if product_kind in ("CORD", "HALF_CORD"):
        # positive multiple of 0.5
        doubled = q * 2
        if doubled != doubled.to_integral_value():
            raise errors.invalid_quantity("CORD/HALF_CORD quantity must be a multiple of 0.5")
    elif product_kind == "PELLET_TON":
        if q != q.to_integral_value():
            raise errors.invalid_quantity("PELLET_TON quantity must be a multiple of 1.0")
    elif product_kind == "PELLET_BAG":
        if q != q.to_integral_value():
            raise errors.invalid_quantity("PELLET_BAG quantity must be a positive integer")


def _make_line(order, product, quantity):
    ts = now_iso()
    lid = new_id()
    per_unit = CORD_EQUIVALENT_PER_UNIT[product["product_kind"]]
    line = {
        "id": lid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "order_id": order["id"],
        "product_id": product["id"],
        "quantity": quantity,
        "unit_price_cents": compute_unit_price_cents(product),
        "cord_equivalent_per_unit": float(per_unit),
        "line_cord_equivalent": line_cord_equivalent(product["product_kind"], quantity),
        "volume_tier_applied": "T0",
        "extended_price_cents": 0,
        "moisture_reading_id": None,
    }
    db.order_lines[lid] = line
    return line


def _order_lines(order):
    return [l for l in db.order_lines.values() if l["order_id"] == order["id"]]


def _validate_order_lines_business(order, lines, check_discontinued=True, check_area=True):
    """Area restriction (9) then discontinued (10) per validation precedence."""
    if check_area:
        for line in lines:
            product = db.products.get(line["product_id"])
            if product:
                check_area_restrictions(
                    order["delivery_postal_code"], order["requested_delivery_date"], product
                )
    if check_discontinued:
        for line in lines:
            product = db.products.get(line["product_id"])
            if product and product.get("discontinued", False):
                raise errors.product_discontinued()


def _find_invoice_for_order(order):
    for inv in db.invoices.values():
        if inv.get("order_id") == order["id"]:
            return inv
    return None


def _release_reservations(order):
    for line in _order_lines(order):
        product = db.products.get(line["product_id"])
        if product:
            product["available_qty"] = dec(product["available_qty"]) + dec(line["quantity"])
            product["reserved_qty"] = dec(product["reserved_qty"]) - dec(line["quantity"])
            product["available_qty"] = float(product["available_qty"])
            product["reserved_qty"] = float(product["reserved_qty"])
            touch(product)


def _issue_refund(order, invoice, amount_cents):
    """Full/partial refund helper used by cancel flows: REFUND event, wallet credit,
    invoice/order payment-status updates."""
    if amount_cents <= 0:
        return
    customer = db.customers.get(order["customer_id"])
    ts = now_iso()
    event = {
        "id": new_id(),
        "created_at": ts,
        "invoice_id": invoice["id"],
        "event_kind": "REFUND",
        "amount_cents": amount_cents,
        "external_ref": f"cancel-{order['id']}-{invoice['refunded_cents']}",
    }
    db.payment_events[event["id"]] = event
    invoice["refunded_cents"] += amount_cents
    if customer:
        credit_wallet(customer, amount_cents)
        touch(customer)
    # Payment axis / invoice status
    if invoice["refunded_cents"] >= invoice["paid_cents"] and invoice["paid_cents"] > 0:
        invoice["status"] = "REFUNDED"
        invoice["settled_at"] = clock.now_iso()
        order["payment_status"] = "REFUNDED"
    else:
        if order["payment_status"] == "PAID":
            order["payment_status"] = "PARTIALLY_REFUNDED"
    touch(invoice)


# ---------------------------------------------------------------------------
# Order create / read
# ---------------------------------------------------------------------------

@bp.post("/api/v1/orders")
def create_order():
    auth = require_roles("Customer", "CustomerService")
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    customer = db.customers.get(customer_id)
    if not customer:
        raise errors.referenced_not_found(f"Customer {customer_id} not found")

    # Ownership: a Customer may only create their own orders
    if auth.is_customer() and auth.user_id != customer_id:
        raise errors.unauthorized("Customers may only create their own orders")

    # Account standing (priority 8)
    if customer["account_status"] != "ACTIVE":
        raise errors.account_inactive()

    delivery_street_address = body.get("delivery_street_address", customer["street_address"])
    if not isinstance(delivery_street_address, str):
        raise errors.validation("delivery_street_address must be a string")
    delivery_postal_code = require_str(body, "delivery_postal_code")
    requested_delivery_date = require_str(body, "requested_delivery_date")
    stacking_addon = body.get("stacking_addon", False)
    if not isinstance(stacking_addon, bool):
        raise errors.validation("stacking_addon must be a boolean")

    subscription_id = body.get("subscription_id")
    sub = None
    if subscription_id is not None:
        sub = db.subscriptions.get(subscription_id)
        if not sub:
            raise errors.referenced_not_found(f"Subscription {subscription_id} not found")
        # Subscription season window (14) is checked before ownership (20)? —
        # Precedence list: 14 (season) comes before 20 (ownership mismatch).
        # PRD §3.5 mentions mismatch first, but §2.8 is the precedence contract.
        if not season_window_contains(sub, requested_delivery_date):
            raise errors.subscription_out_of_season()
        if sub["customer_id"] != customer_id:
            raise errors.subscription_mismatch()

    lines_input = body.get("lines", [])
    if not isinstance(lines_input, list):
        raise errors.validation("lines must be an array")

    # Resolve products and validate quantities BEFORE creating anything
    resolved = []
    for li in lines_input:
        if not isinstance(li, dict):
            raise errors.validation("each line must be an object")
        product_id = require_str(li, "product_id")
        product = db.products.get(product_id)
        if not product:
            raise errors.referenced_not_found(f"Product {product_id} not found")
        quantity = require_number(li, "quantity")
        resolved.append((product, quantity))

    # Area restriction (9) before discontinued (10) before quantity (11)
    for product, _q in resolved:
        check_area_restrictions(delivery_postal_code, requested_delivery_date, product)
    for product, _q in resolved:
        if product.get("discontinued", False):
            raise errors.product_discontinued()
    for product, q in resolved:
        _validate_quantity(product["product_kind"], q)

    ts = now_iso()
    oid = new_id()
    order = {
        "id": oid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "delivery_window_id": None,
        "delivery_street_address": delivery_street_address,
        "delivery_postal_code": delivery_postal_code,
        "requested_delivery_date": requested_delivery_date,
        "payment_status": "UNPAID",
        "fulfillment_status": "DRAFT",
        "stacking_addon": stacking_addon,
        "stacking_fee_cents": 0,
        "subtotal_cents": 0,
        "volume_discount_cents": 0,
        "subscription_discount_cents": 0,
        "loyalty_discount_cents": 0,
        "seasonal_surcharge_cents": 0,
        "delivery_fee_cents": 0,
        "total_cents": 0,
        "total_cord_equivalent": 0,
        "scheduled_at": None,
        "delivered_at": None,
        "cancelled_reason": None,
    }
    db.orders[oid] = order
    lines = [_make_line(order, p, q) for p, q in resolved]
    recompute_order_pricing(order, lines)
    return success_object(serialize_order(order), status=201)


@bp.get("/api/v1/orders/<oid>")
def get_order(oid):
    auth = require_roles("Customer", "CustomerService", "OperationsManager", "RoutePlanner", "Driver")
    order = _get_order_or_404(oid)
    _check_customer_owns_order(auth, order)
    return success_object(serialize_order(order))


@bp.get("/api/v1/orders")
def list_orders():
    auth = require_roles("CustomerService", "OperationsManager", "RoutePlanner", "Driver", "Customer")
    limit, offset = parse_pagination()
    items = list(db.orders.values())
    if auth.is_customer():
        items = [o for o in items if o["customer_id"] == auth.user_id]
    for f in ("customer_id", "subscription_id", "delivery_window_id", "fulfillment_status", "payment_status"):
        v = request.args.get(f)
        if v is not None:
            items = [o for o in items if str(o.get(f)) == v]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_order(o) for o in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------

@bp.post("/api/v1/orders/<oid>/lines")
def add_line(oid):
    auth = require_roles("Customer", "CustomerService")
    order = _get_order_or_404(oid)
    _check_customer_owns_order(auth, order)
    body = get_json_body()
    product_id = require_str(body, "product_id")
    product = db.products.get(product_id)
    if not product:
        raise errors.referenced_not_found(f"Product {product_id} not found")
    quantity = require_number(body, "quantity")
    # State: order must be DRAFT to edit lines
    if order["fulfillment_status"] != "DRAFT":
        raise errors.invalid_state("Lines may only be added to DRAFT orders")
    # Area (9) -> discontinued (10) -> quantity (11)
    check_area_restrictions(order["delivery_postal_code"], order["requested_delivery_date"], product)
    if product.get("discontinued", False):
        raise errors.product_discontinued()
    _validate_quantity(product["product_kind"], quantity)
    line = _make_line(order, product, quantity)
    recompute_order_pricing(order, _order_lines(order))
    touch(order)
    return success_object(serialize_order_line(line), status=201)


@bp.get("/api/v1/orders/<oid>/lines")
def list_order_lines(oid):
    auth = require_roles("Customer", "CustomerService", "OperationsManager", "Driver", "RoutePlanner")
    order = _get_order_or_404(oid)
    _check_customer_owns_order(auth, order)
    limit, offset = parse_pagination()
    page, total = paginate(_order_lines(order), limit, offset)
    return success_list([serialize_order_line(l) for l in page], total, limit, offset)


@bp.get("/api/v1/order-lines/<lid>")
def get_order_line(lid):
    auth = require_roles("Customer", "CustomerService", "OperationsManager", "Driver", "RoutePlanner")
    line = _get_line_or_404(lid)
    order = db.orders.get(line["order_id"])
    if order:
        _check_customer_owns_order(auth, order)
    return success_object(serialize_order_line(line))


@bp.get("/api/v1/order-lines")
def list_order_lines_global():
    require_roles("CustomerService", "OperationsManager", "RoutePlanner")
    limit, offset = parse_pagination()
    items = list(db.order_lines.values())
    for f in ("product_id", "moisture_reading_id", "order_id"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if str(l.get(f)) == v]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_order_line(l) for l in page], total, limit, offset)


@bp.patch("/api/v1/order-lines/<lid>")
def update_order_line(lid):
    auth = require_roles("Customer", "CustomerService")
    line = _get_line_or_404(lid)
    order = db.orders.get(line["order_id"])
    if not order:
        raise errors.not_found("Parent order not found")
    _check_customer_owns_order(auth, order)
    body = get_json_body()
    quantity = require_number(body, "quantity")
    if order["fulfillment_status"] != "DRAFT":
        raise errors.invalid_state("Lines may only be edited on DRAFT orders")
    product = db.products.get(line["product_id"])
    _validate_quantity(product["product_kind"], quantity)
    line["quantity"] = quantity
    line["line_cord_equivalent"] = line_cord_equivalent(product["product_kind"], quantity)
    touch(line)
    recompute_order_pricing(order, _order_lines(order))
    touch(order)
    return success_object(serialize_order_line(line))


@bp.delete("/api/v1/order-lines/<lid>")
def delete_order_line(lid):
    auth = require_roles("Customer", "CustomerService")
    line = _get_line_or_404(lid)
    order = db.orders.get(line["order_id"])
    if not order:
        raise errors.not_found("Parent order not found")
    _check_customer_owns_order(auth, order)
    if order["fulfillment_status"] != "DRAFT":
        raise errors.invalid_state("Lines may only be removed from DRAFT orders")
    del db.order_lines[lid]
    recompute_order_pricing(order, _order_lines(order))
    touch(order)
    return success_empty(status=204)


# ---------------------------------------------------------------------------
# Submit / schedule / dispatch / deliver / fail / cancel
# ---------------------------------------------------------------------------

@bp.post("/api/v1/orders/<oid>/submit")
def submit_order(oid):
    auth = require_roles("Customer", "CustomerService")
    order = _get_order_or_404(oid)
    _check_customer_owns_order(auth, order)
    if order["fulfillment_status"] != "DRAFT":
        raise errors.invalid_state("Order is not DRAFT")
    customer = db.customers.get(order["customer_id"])
    # Account standing (8)
    if not customer or customer["account_status"] != "ACTIVE":
        raise errors.account_inactive()
    lines = _order_lines(order)
    if not lines:
        raise errors.invalid_state("Order has no lines")
    # Area restriction re-check (9), discontinued (10)
    _validate_order_lines_business(order, lines)
    # Subscription must be ACTIVE and date in season window (state / 14)
    if order.get("subscription_id"):
        sub = db.subscriptions.get(order["subscription_id"])
        if not sub or sub["status"] != "ACTIVE":
            raise errors.invalid_state("Subscription is not ACTIVE")
        if not season_window_contains(sub, order["requested_delivery_date"]):
            raise errors.subscription_out_of_season()
    # Stock availability (17)
    for line in lines:
        product = db.products.get(line["product_id"])
        if not product or dec(product["available_qty"]) < dec(line["quantity"]):
            raise errors.insufficient_stock()
    # Reserve stock
    for line in lines:
        product = db.products.get(line["product_id"])
        product["available_qty"] = float(dec(product["available_qty"]) - dec(line["quantity"]))
        product["reserved_qty"] = float(dec(product["reserved_qty"]) + dec(line["quantity"]))
        touch(product)
    # Recompute pricing, transition, issue invoice
    recompute_order_pricing(order, lines)
    order["fulfillment_status"] = "PENDING_PAYMENT"
    touch(order)

    customer = db.customers.get(order["customer_id"])
    season_year = None
    if order.get("subscription_id"):
        sub = db.subscriptions.get(order["subscription_id"])
        if sub:
            season_year = sub["season_year"]
    if season_year is None:
        # Derive a season year from requested_delivery_date for invoice numbering:
        # season starts Nov 1; Nov/Dec belong to that year's season, Jan–Oct to previous.
        rdd = order["requested_delivery_date"]
        y = int(rdd[0:4]); m = int(rdd[5:7])
        season_year = y if m >= 11 else y - 1
    ts = now_iso()
    invoice = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "order_id": order["id"],
        "invoice_number": next_invoice_number(season_year),
        "amount_cents": order["total_cents"],
        "paid_cents": 0,
        "refunded_cents": 0,
        "status": "OPEN",
        "due_date": invoice_due_date(order["requested_delivery_date"]),
        "issued_at": clock.now_iso(),
        "settled_at": None,
    }
    db.invoices[invoice["id"]] = invoice
    return success_object(serialize_order(order))


@bp.post("/api/v1/orders/<oid>/schedule")
def schedule_order(oid):
    require_roles("RoutePlanner")
    order = _get_order_or_404(oid)
    body = get_json_body()
    delivery_window_id = require_str(body, "delivery_window_id")
    window = db.delivery_windows.get(delivery_window_id)
    if not window:
        raise errors.referenced_not_found(f"DeliveryWindow {delivery_window_id} not found")
    expected_order_version = require_int(body, "expected_order_version")

    # State (5): must be CONFIRMED or DELIVERY_FAILED
    if order["fulfillment_status"] not in ("CONFIRMED", "DELIVERY_FAILED"):
        raise errors.invalid_state("Order is not in a schedulable state")
    # OCC (6)
    if expected_order_version != order["version"]:
        raise errors.stale_version("expected_order_version does not match")
    # Window must be OPEN (13 — window closed for scheduling covers non-OPEN windows)
    if window["status"] != "OPEN":
        raise errors.window_closed("Window is not OPEN")
    # Cutoff (13): strictly before day-before cutoff
    now = clock.now()
    if not (now < day_before_cutoff(window)):
        raise errors.window_closed("Past the day-before scheduling cutoff")
    # Capacity (16): equality permitted
    if dec(window["committed_cord_equivalent"]) + dec(order["total_cord_equivalent"]) > dec(window["capacity_cord_equivalent"]):
        raise errors.window_capacity()

    # Side effects
    order["delivery_window_id"] = delivery_window_id
    window["committed_cord_equivalent"] = float(
        dec(window["committed_cord_equivalent"]) + dec(order["total_cord_equivalent"])
    )
    touch(window)
    # Auto-close when full
    if dec(window["committed_cord_equivalent"]) >= dec(window["capacity_cord_equivalent"]):
        window["status"] = "CLOSED"
        touch(window)
    order["fulfillment_status"] = "SCHEDULED"
    order["scheduled_at"] = clock.now_iso()
    touch(order)
    # Delivery fee becomes final once scheduled
    recompute_order_pricing(order, _order_lines(order))
    return success_object(serialize_order(order))


@bp.post("/api/v1/orders/<oid>/dispatch")
def dispatch_order(oid):
    require_roles("Driver")
    order = _get_order_or_404(oid)
    if order["fulfillment_status"] != "SCHEDULED":
        raise errors.invalid_state("Order is not SCHEDULED")
    window = db.delivery_windows.get(order.get("delivery_window_id"))
    if not window or window["status"] != "LOCKED":
        raise errors.invalid_state("Delivery window is not LOCKED")
    now = clock.now()
    sd = window["service_date"]
    if (now.year, now.month, now.day) != (int(sd[0:4]), int(sd[5:7]), int(sd[8:10])):
        raise errors.invalid_state("Current date is not the window service date")
    if not (window["start_hour"] <= now.hour < window["end_hour"]):
        raise errors.invalid_state("Current time is outside the window hours")
    order["fulfillment_status"] = "OUT_FOR_DELIVERY"
    touch(order)
    return success_object(serialize_order(order))


@bp.post("/api/v1/orders/<oid>/deliver")
def deliver_order(oid):
    require_roles("Driver")
    order = _get_order_or_404(oid)
    if order["fulfillment_status"] != "OUT_FOR_DELIVERY":
        raise errors.invalid_state("Order is not OUT_FOR_DELIVERY")
    # Moisture gate (21): every line needs a passing reading within last 24 logical hours
    now = clock.now()
    for line in _order_lines(order):
        readings = [
            r for r in db.moisture_readings.values()
            if r["order_line_id"] == line["id"] and r["reading_pass"]
        ]
        fresh = None
        for r in readings:
            rt = datetime.fromisoformat(r["recorded_at"].replace("Z", "+00:00"))
            if now - rt <= timedelta(hours=24):
                fresh = r
                break
        if fresh is None:
            raise errors.moisture_check_failed()
    # Side effects: release reserved stock
    for line in _order_lines(order):
        product = db.products.get(line["product_id"])
        if product:
            product["reserved_qty"] = float(dec(product["reserved_qty"]) - dec(line["quantity"]))
            touch(product)
    customer = db.customers.get(order["customer_id"])
    delivered_at = clock.now()
    order["fulfillment_status"] = "DELIVERED"
    order["delivered_at"] = clock.now_iso()
    touch(order)
    if customer:
        customer["lifetime_cord_equivalent_delivered"] = float(
            dec(customer.get("lifetime_cord_equivalent_delivered", 0)) + dec(order["total_cord_equivalent"])
        )
        recompute_loyalty_tier(customer)
        touch(customer)
    # Subscription accrual
    if order.get("subscription_id") and customer:
        sub = db.subscriptions.get(order["subscription_id"])
        if sub and sub["status"] == "ACTIVE" and season_window_contains(sub, order["requested_delivery_date"]):
            sub["delivered_cord_equivalent"] = float(
                dec(sub["delivered_cord_equivalent"]) + dec(order["total_cord_equivalent"])
            )
            touch(sub)
            if dec(sub["delivered_cord_equivalent"]) >= dec(sub["commitment_cord_equivalent"]):
                sub["status"] = "FULFILLED"
                sub["closed_at"] = clock.now_iso()
                touch(sub)
        # Clawback reconciliation: if the subscription was CANCELLED within 7
        # logical days and this order was SCHEDULED at cancellation time, fold
        # its subscription discount into the clawback via ADJUST_CREDIT.
        if sub and sub["status"] == "CANCELLED" and sub.get("_clawback_at"):
            cancelled_at = datetime.fromisoformat(sub["_clawback_at"].replace("Z", "+00:00"))
            if delivered_at - cancelled_at <= timedelta(days=7):
                delta = order.get("subscription_discount_cents", 0)
                if delta > 0:
                    debit_wallet(customer, delta)
                    touch(customer)
                    inv = _find_invoice_for_order(order)
                    ts = now_iso()
                    ev = {
                        "id": new_id(),
                        "created_at": ts,
                        "invoice_id": inv["id"] if inv else None,
                        "event_kind": "ADJUST_CREDIT",
                        "amount_cents": delta,
                        "external_ref": f"clawback-reconcile-{order['id']}",
                    }
                    db.payment_events[ev["id"]] = ev
                    sub["_clawback_paid"] = sub.get("_clawback_paid", 0) + delta
    return success_object(serialize_order(order))


@bp.post("/api/v1/orders/<oid>/fail-delivery")
def fail_delivery(oid):
    auth = require_roles("Driver")
    order = _get_order_or_404(oid)
    if order["fulfillment_status"] != "OUT_FOR_DELIVERY":
        raise errors.invalid_state("Order is not OUT_FOR_DELIVERY")
    body = get_json_body() if request.is_json else {}
    reason = body.get("reason")
    if not reason:
        raise errors.validation("reason is required")
    order["fulfillment_status"] = "DELIVERY_FAILED"
    order["cancelled_reason"] = reason
    # Track failure for the self-override guard
    order["_last_failure"] = {"driver_id": auth.user_id, "at": clock.now_iso()}
    window = db.delivery_windows.get(order.get("delivery_window_id"))
    if window:
        window["committed_cord_equivalent"] = float(
            dec(window["committed_cord_equivalent"]) - dec(order["total_cord_equivalent"])
        )
        touch(window)
    touch(order)
    return success_object(serialize_order(order))


@bp.post("/api/v1/orders/<oid>/cancel")
def cancel_order(oid):
    auth = require_roles("Customer", "CustomerService", "OperationsManager")
    order = _get_order_or_404(oid)
    body = get_json_body() if request.is_json else {}
    reason = body.get("reason")
    fs = order["fulfillment_status"]

    # Cancellability (19)
    if fs in ("OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"):
        raise errors.not_cancellable()

    is_owner = auth.is_customer() and auth.user_id == order["customer_id"]
    is_admin = auth.is_ops_manager()
    is_cs = auth.role == "CustomerService"

    if fs == "DELIVERY_FAILED":
        if not is_admin:
            raise errors.unauthorized("Only OperationsManager may cancel a DELIVERY_FAILED order")
    elif fs == "DRAFT":
        if not (is_owner or is_admin or is_cs):
            raise errors.unauthorized()
    elif fs in ("PENDING_PAYMENT", "CONFIRMED"):
        if not (is_owner or is_admin or is_cs):
            raise errors.unauthorized()
    elif fs == "SCHEDULED":
        window = db.delivery_windows.get(order.get("delivery_window_id"))
        before_cutoff = True
        if window:
            before_cutoff = clock.now() < day_before_cutoff(window)
        if auth.is_customer():
            # Customer may cancel only before cutoff, and only own orders
            if not is_owner:
                raise errors.unauthorized()
            if not before_cutoff:
                raise errors.invalid_state("Inside the 24-hour lock window; only OperationsManager may cancel")
        elif not (is_admin or is_cs):
            raise errors.unauthorized()
    else:
        raise errors.not_cancellable()

    cancellation_fee = 0
    if fs == "SCHEDULED":
        window = db.delivery_windows.get(order.get("delivery_window_id"))
        if window:
            cancellation_fee = compute_cancellation_fee(order, window, auth.role, clock.now())
            # Window capacity release + conditional re-open
            window["committed_cord_equivalent"] = float(
                dec(window["committed_cord_equivalent"]) - dec(order["total_cord_equivalent"])
            )
            if window["status"] == "CLOSED" and dec(window["committed_cord_equivalent"]) < dec(window["capacity_cord_equivalent"]):
                window["status"] = "OPEN"
            touch(window)

    # Reservation release (not for DRAFT which never reserved)
    if fs in ("PENDING_PAYMENT", "CONFIRMED", "SCHEDULED", "DELIVERY_FAILED"):
        _release_reservations(order)

    # Refund whatever was paid (if anything)
    invoice = _find_invoice_for_order(order)
    if invoice and invoice["paid_cents"] > invoice["refunded_cents"]:
        _issue_refund(order, invoice, invoice["paid_cents"] - invoice["refunded_cents"])

    order["fulfillment_status"] = "CANCELLED"
    order["cancelled_reason"] = reason
    if cancellation_fee:
        order["_cancellation_fee_cents"] = cancellation_fee
    touch(order)
    return success_object(serialize_order(order))


# ---------------------------------------------------------------------------
# Payment events (order payment axis)
# ---------------------------------------------------------------------------

@bp.post("/api/v1/orders/<oid>/payments")
def post_payment(oid):
    require_roles("CustomerService", "OperationsManager")
    order = _get_order_or_404(oid)
    body = get_json_body()
    event_kind = require_str(body, "event_kind")
    if event_kind not in ("AUTHORIZE", "CAPTURE", "REFUND", "CHARGEBACK", "ADJUST_CREDIT"):
        raise errors.validation("Invalid event_kind")
    amount = require_int(body, "amount_cents")
    external_ref = require_str(body, "external_ref")

    invoice = _find_invoice_for_order(order)
    if not invoice:
        raise errors.invalid_state("Order has no invoice")

    # Uniqueness of external_ref per (invoice_id, event_kind, external_ref)
    for ev in db.payment_events.values():
        if (
            ev["invoice_id"] == invoice["id"]
            and ev["event_kind"] == event_kind
            and ev["external_ref"] == external_ref
        ):
            raise errors.validation("external_ref must be unique per invoice and event kind")

    customer = db.customers.get(order["customer_id"])
    ts = now_iso()

    def persist_event():
        ev = {
            "id": new_id(),
            "created_at": ts,
            "invoice_id": invoice["id"],
            "event_kind": event_kind,
            "amount_cents": amount,
            "external_ref": external_ref,
        }
        db.payment_events[ev["id"]] = ev
        return ev

    if event_kind == "AUTHORIZE":
        if order["payment_status"] != "UNPAID" or order["fulfillment_status"] != "PENDING_PAYMENT":
            raise errors.invalid_state("Order is not in an authorizable state")
        # A negative or zero amount is treated as a decline? PRD: declined
        # authorization persists the declined event and moves to PAYMENT_FAILED.
        # We treat a positive amount as success; <= 0 as decline.
        if amount <= 0:
            ev = persist_event()
            order["payment_status"] = "PAYMENT_FAILED"
            touch(order)
            touch(invoice)
            return success_object(serialize_payment_event(ev), status=201)
        order["payment_status"] = "AUTHORIZED"
        ev = persist_event()
        touch(order)
        touch(invoice)
        return success_object(serialize_payment_event(ev), status=201)

    if event_kind == "CAPTURE":
        if order["payment_status"] != "AUTHORIZED":
            raise errors.invalid_state("Order payment is not AUTHORIZED")
        due = invoice["amount_cents"] - invoice["paid_cents"]
        if amount != due:
            raise errors.invalid_state("Capture amount must equal the outstanding invoice amount")
        ev = persist_event()
        invoice["paid_cents"] += amount
        invoice["status"] = "PAID" if invoice["paid_cents"] >= invoice["amount_cents"] else "PARTIALLY_PAID"
        if invoice["status"] == "PAID":
            invoice["settled_at"] = clock.now_iso()
        order["payment_status"] = "PAID"
        touch(invoice)
        touch(order)
        # Cascade: PENDING_PAYMENT -> CONFIRMED
        if order["fulfillment_status"] == "PENDING_PAYMENT":
            order["fulfillment_status"] = "CONFIRMED"
            touch(order)
        return success_object(serialize_payment_event(ev), status=201)

    if event_kind == "REFUND":
        # Refund range (22)
        unrefunded = invoice["paid_cents"] - invoice["refunded_cents"]
        if amount <= 0 or amount > unrefunded:
            raise errors.invalid_refund_amount()
        if order["payment_status"] not in ("PAID", "PARTIALLY_REFUNDED"):
            raise errors.invalid_state("Order is not in a refundable state")
        ev = persist_event()
        invoice["refunded_cents"] += amount
        if customer:
            credit_wallet(customer, amount)
            recompute_loyalty_tier(customer)
            touch(customer)
        if invoice["refunded_cents"] >= invoice["paid_cents"]:
            invoice["status"] = "REFUNDED"
            invoice["settled_at"] = clock.now_iso()
            order["payment_status"] = "REFUNDED"
        else:
            order["payment_status"] = "PARTIALLY_REFUNDED"
        touch(invoice)
        touch(order)
        return success_object(serialize_payment_event(ev), status=201)

    if event_kind == "CHARGEBACK":
        ev = persist_event()
        if customer:
            debit_wallet(customer, amount)
            recompute_loyalty_tier(customer)
            touch(customer)
        touch(invoice)
        touch(order)
        return success_object(serialize_payment_event(ev), status=201)

    if event_kind == "ADJUST_CREDIT":
        ev = persist_event()
        if customer:
            if amount >= 0:
                debit_wallet(customer, amount)
            else:
                credit_wallet(customer, -amount)
            recompute_loyalty_tier(customer)
            touch(customer)
        touch(invoice)
        touch(order)
        return success_object(serialize_payment_event(ev), status=201)

    raise errors.validation("Unsupported event_kind")


# reset-failure is part of the payments surface (PRD §3.8): from PAYMENT_FAILED back to UNPAID
@bp.post("/api/v1/orders/<oid>/payments/reset-failure")
def reset_payment_failure(oid):
    require_roles("CustomerService", "OperationsManager")
    order = _get_order_or_404(oid)
    if order["payment_status"] != "PAYMENT_FAILED":
        raise errors.invalid_state("Order payment is not PAYMENT_FAILED")
    order["payment_status"] = "UNPAID"
    touch(order)
    return success_object(serialize_order(order))
