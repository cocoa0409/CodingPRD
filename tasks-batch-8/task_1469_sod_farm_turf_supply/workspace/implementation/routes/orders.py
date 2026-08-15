"""Orders: confirm (cutoff + capacity + allocation), lifecycle transitions,
delivery checks, payments."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
import db
import services
from auth import check_ownership, require_roles
from db import sub_fields
from errors import (err, ERR_ALREADY_TERMINAL, ERR_BATCH_NOT_FRESH,
                    ERR_CAPACITY_EXCEEDED, ERR_CUTOFF_PASSED, ERR_DELIVERY_STALE,
                    ERR_INVALID_ENUM, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_FOUND, ERR_ORDER_UNDER_ALLOCATED,
                    ERR_PAYMENT_AMOUNT_MISMATCH)
from serialize import (order_allocated_sqft, order_total_paid,
                       pub_delivery_check, pub_order, pub_payment)
from util import (D, as_num, as_str, body, hours_between, ok, ok_list, paged,
                  pagination, parse_dt, r2, require, sort_created)

bp = Blueprint("orders", __name__)

TERMINAL_ORDER_STATES = {"CLOSED", "CANCELLED"}
PAYMENT_METHODS = {"CHECK", "CARD"}


def _get_order(oid):
    order = db.store.orders.get(oid)
    if order is None:
        raise err(ERR_NOT_FOUND, f"order {oid} not found")
    return order


def _order_config(order):
    return calc.config_or_defaults(db.store.price_configs.get(order["price_config_id"]))


def _guard_not_terminal(order):
    if order["status"] in TERMINAL_ORDER_STATES:
        raise err(ERR_ALREADY_TERMINAL, f"order {order['id']} is {order['status']}")


@bp.route("/orders", methods=["GET"])
def list_orders():
    require_roles("SalesRep", "FarmManager")
    limit, offset = pagination()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    price_config_id = request.args.get("price_config_id")
    items = sort_created(db.store.orders.values())
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if price_config_id is not None:
        items = [o for o in items if o["price_config_id"] == price_config_id]
    page, total = paged(items, limit, offset)
    return ok_list([pub_order(o) for o in page], total, limit, offset)


@bp.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = require_roles("SalesRep", "FarmManager", "Customer")
    order = _get_order(oid)
    check_ownership(user_id, role, order["customer_id"])
    return ok(pub_order(order), 200)


@bp.route("/orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    require_roles("SalesRep")
    order = _get_order(oid)
    cfg = _order_config(order)
    payload = body()
    # tier 4: window shape — on delivery_date, hour-aligned, within start bounds
    window_start = parse_dt(require(payload, "delivery_window_start"),
                            "delivery_window_start")
    if (window_start.minute != 0 or window_start.second != 0
            or window_start.microsecond != 0):
        raise err(ERR_INVALID_REQUEST, "delivery_window_start must be hour-aligned")
    if window_start.date() != order["delivery_date"]:
        raise err(ERR_INVALID_REQUEST,
                  "delivery_window_start must fall on the order's delivery_date")
    if not (int(cfg["delivery_earliest_start_hour"]) <= window_start.hour
            <= int(cfg["delivery_latest_start_hour"])):
        raise err(ERR_INVALID_REQUEST,
                  f"delivery_window_start hour must be in "
                  f"[{cfg['delivery_earliest_start_hour']}, {cfg['delivery_latest_start_hour']}]")
    window_end = window_start + timedelta(hours=int(cfg["delivery_window_hours"]))
    # tier 6/7: state guards
    _guard_not_terminal(order)
    if order["status"] != "PLACED":
        raise err(ERR_INVALID_STATE, f"order {oid} is {order['status']}, not PLACED")
    # tier 9: confirm cutoff (strict <)
    if not (db.now() < calc.confirm_cutoff(order, cfg)):
        raise err(ERR_CUTOFF_PASSED, "confirm cutoff has passed for this order")
    # tier 11/12: allocation freshness first, then truck capacity, then quantity
    quote = db.store.quotes.get(order["quote_id"])
    status, selection = calc.try_allocate(quote, cfg, window_end)
    if status == "not_fresh":
        raise err(ERR_BATCH_NOT_FRESH,
                  "matching batches exist but all fail the freshness projection")
    if calc.zone_consumers(order["capacity_zone"], window_start, window_end) \
            >= int(cfg["zone_truck_capacity"]):
        raise err(ERR_CAPACITY_EXCEEDED, "zone truck capacity reached for this window")
    if status == "under":
        raise err(ERR_ORDER_UNDER_ALLOCATED,
                  "allocation cannot meet the quote line quantities")
    # commit: link batches, book the window
    for b in selection:
        b["order_id"] = order["id"]
        db.bump(b)
    order["status"] = "CONFIRMED"
    order["delivery_window_start"] = window_start
    order["delivery_window_end"] = window_end
    db.bump(order)
    return ok(pub_order(order), 200)


@bp.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    require_roles("SalesRep")
    order = _get_order(oid)
    _guard_not_terminal(order)
    if order["status"] not in ("PLACED", "CONFIRMED", "OUT_FOR_DELIVERY"):
        raise err(ERR_INVALID_STATE,
                  f"order {oid} in {order['status']} cannot be cancelled")
    if order_total_paid(order) > 0:
        raise err(ERR_INVALID_STATE, "paid orders require a credit workflow")
    order["status"] = "CANCELLED"
    services.cancel_order_cascade(order)
    db.bump(order)
    return ok(pub_order(order), 200)


@bp.route("/orders/<oid>/dispatch", methods=["POST"])
def dispatch_order(oid):
    require_roles("FleetManager")
    order = _get_order(oid)
    _guard_not_terminal(order)
    if order["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, f"order {oid} is {order['status']}, not CONFIRMED")
    for b in db.store.harvest_batches.values():
        if b["order_id"] == oid and b["status"] != "CANCELLED" and b["status"] != "COMPLETE":
            raise err(ERR_INVALID_STATE, "every linked batch must be COMPLETE to dispatch")
    if db.today() != order["delivery_date"]:
        raise err(ERR_INVALID_STATE, "orders may only dispatch on the delivery date")
    order["status"] = "OUT_FOR_DELIVERY"
    db.bump(order)
    return ok(pub_order(order), 200)


@bp.route("/orders/<oid>/mark-delivered", methods=["POST"])
def mark_delivered(oid):
    require_roles("FleetManager")
    order = _get_order(oid)
    cfg = _order_config(order)
    payload = body()
    # tier 4: shape — accepted_sqft >= 0 and within remaining allocation
    accepted = as_num(require(payload, "accepted_sqft"), "accepted_sqft", minimum=0)
    allocated = order_allocated_sqft(order)
    if D(order["delivered_sqft"]) + accepted > allocated:
        raise err(ERR_INVALID_REQUEST,
                  "delivered_sqft + accepted_sqft exceeds allocated_sqft")
    # tier 6/7: state guards (DELIVERED -> DELIVERED is the top-up self-loop)
    _guard_not_terminal(order)
    if order["status"] not in ("OUT_FOR_DELIVERY", "DELIVERED"):
        raise err(ERR_INVALID_STATE,
                  f"order {oid} is {order['status']}; cannot record a delivery")
    # tier 11: freshness against the actual harvest
    linked_ends = [b["actual_harvest_end"] for b in db.store.harvest_batches.values()
                   if b["order_id"] == oid and b["status"] != "CANCELLED"
                   and b["actual_harvest_end"] is not None]
    freshness = Decimal("0")
    if linked_ends:
        freshness = hours_between(min(linked_ends), db.now())
        if freshness > D(cfg["freshness_limit_hours"]):
            raise err(ERR_DELIVERY_STALE,
                      "delivery exceeds the freshness window; order stays OUT_FOR_DELIVERY")
    first_delivery = order["actual_delivered_at"] is None
    order["status"] = "DELIVERED"
    order["delivered_sqft"] = D(order["delivered_sqft"]) + accepted
    if first_delivery:
        order["actual_delivered_at"] = db.now()
    order["freshness_hours"] = r2(freshness)
    db.bump(order)
    return ok(pub_order(order), 200)


@bp.route("/orders/<oid>/install-start", methods=["POST"])
def install_start(oid):
    user_id, role = require_roles("Customer")
    order = _get_order(oid)
    check_ownership(user_id, role, order["customer_id"])
    _guard_not_terminal(order)
    if order["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE, f"order {oid} is {order['status']}, not DELIVERED")
    order["status"] = "INSTALLING"
    order["install_started_at"] = db.now()
    db.bump(order)
    return ok(pub_order(order), 200)


@bp.route("/orders/<oid>/install-complete", methods=["POST"])
def install_complete(oid):
    user_id, role = require_roles("Customer")
    order = _get_order(oid)
    check_ownership(user_id, role, order["customer_id"])
    _guard_not_terminal(order)
    if order["status"] != "INSTALLING":
        raise err(ERR_INVALID_STATE, f"order {oid} is {order['status']}, not INSTALLING")
    order["installed_at"] = db.now()
    # parallel dimensions auto-join: already PAID -> straight to CLOSED
    order["status"] = "CLOSED" if order["payment_status"] == "PAID" else "INSTALLED"
    db.bump(order)
    return ok(pub_order(order), 200)


@bp.route("/orders/<oid>/close", methods=["POST"])
def close_order(oid):
    require_roles("SalesRep")
    order = _get_order(oid)
    _guard_not_terminal(order)
    if order["status"] != "DELIVERED":
        raise err(ERR_INVALID_STATE, f"order {oid} is {order['status']}, not DELIVERED")
    if order["payment_status"] != "PAID":
        raise err(ERR_INVALID_STATE, "order must be fully paid before closing")
    order["status"] = "CLOSED"
    db.bump(order)
    return ok(pub_order(order), 200)


# ------------------------------------------------------------- delivery checks
@bp.route("/orders/<oid>/delivery-checks", methods=["POST"])
def create_delivery_check(oid):
    require_roles("SalesRep")
    order = _get_order(oid)
    _guard_not_terminal(order)
    existing = sort_created(c for c in db.store.delivery_checks.values()
                            if c["order_id"] == oid)
    if len(existing) >= 2:
        raise err(ERR_INVALID_STATE, "at most two delivery checks per order")
    check_index = len(existing) + 1
    prev_cumulative = existing[-1]["delivered_cumulative"] if existing else Decimal("0")
    computed = calc.delivery_check_compute(order, check_index, prev_cumulative,
                                           order_total_paid(order))
    check = sub_fields()
    check.update({"order_id": oid, "check_index": check_index})
    check.update(computed)
    db.store.delivery_checks[check["id"]] = check
    # fiscal reconciliation: chargeable rewritten, flag set/cleared, PAID can revert
    order["chargeable_amount"] = computed["chargeable_after"]
    order["delivery_flagged"] = not computed["in_window"]
    services.reconcile_order(order)
    db.bump(order)
    return ok(pub_delivery_check(check), 201)


@bp.route("/orders/<oid>/delivery-checks", methods=["GET"])
def list_delivery_checks(oid):
    user_id, role = require_roles("SalesRep", "FarmManager", "Customer")
    order = _get_order(oid)
    check_ownership(user_id, role, order["customer_id"])
    limit, offset = pagination()
    items = sort_created(c for c in db.store.delivery_checks.values()
                         if c["order_id"] == oid)
    page, total = paged(items, limit, offset)
    return ok_list([pub_delivery_check(c) for c in page], total, limit, offset)


# ------------------------------------------------------------------- payments
@bp.route("/orders/<oid>/payments", methods=["POST"])
def create_payment(oid):
    require_roles("SalesRep")
    order = _get_order(oid)
    payload = body()
    # tier 4: shape
    amount = as_num(require(payload, "amount"), "amount")
    if "method" not in payload or payload["method"] is None:
        raise err(ERR_INVALID_REQUEST, "method is required")
    # tier 5: enum membership
    if payload["method"] not in PAYMENT_METHODS:
        raise err(ERR_INVALID_ENUM, "method must be CHECK or CARD")
    # tier 6: terminal guard (beats a wrong-amount rejection)
    _guard_not_terminal(order)
    # tier 12: exact-amount instrument against the current amount due
    total_paid = order_total_paid(order)
    amount_due = max(Decimal("0"), D(order["chargeable_amount"]) - total_paid)
    if amount_due <= 0 or amount != amount_due:
        raise err(ERR_PAYMENT_AMOUNT_MISMATCH,
                  f"payment amount must equal the current amount_due ({amount_due})")
    payment = sub_fields()
    payment.update({
        "order_id": oid,
        "amount": amount,
        "method": payload["method"],
        "received_at": payment["created_at"],
    })
    db.store.payments[payment["id"]] = payment
    services.reconcile_order(order)
    db.bump(order)
    return ok(pub_payment(payment), 201)


@bp.route("/orders/<oid>/payments", methods=["GET"])
def list_payments(oid):
    user_id, role = require_roles("SalesRep", "FarmManager", "Customer")
    order = _get_order(oid)
    check_ownership(user_id, role, order["customer_id"])
    limit, offset = pagination()
    items = sort_created(p for p in db.store.payments.values() if p["order_id"] == oid)
    page, total = paged(items, limit, offset)
    return ok_list([pub_payment(p) for p in page], total, limit, offset)
