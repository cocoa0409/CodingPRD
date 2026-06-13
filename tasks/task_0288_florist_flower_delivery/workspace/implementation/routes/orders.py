"""Order routes and the parallel (fulfillment + payment) state machine
(PRD §3.2-§3.6)."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_auth, require_role
from helpers import (
    get_body, make_record, touch, public, parse_pagination, paginate,
    require_fields, as_int, as_str, as_bool, as_enum,
)
from response import success, success_list
from services import clock
from services import pricing

bp = Blueprint("orders", __name__)

OCCASIONS = {"GENERAL", "BIRTHDAY", "ANNIVERSARY", "SYMPATHY", "ROMANCE"}


# ---------------------------------------------------------------------------
# Ownership helper (PRD §2.1): Customer acts on own Order via customer_id.
# ---------------------------------------------------------------------------
def _check_order_owner(order, user_id, role):
    if role == "Customer" and order["customer_id"] != user_id:
        raise errors.not_resource_owner("Customer does not own this order")


def _validate_window(start, end):
    if start < 0 or start > 1439:
        raise errors.invalid_request("window_start_minute must be 0..1439")
    if end > 1440:
        raise errors.invalid_request("window_end_minute must be <= 1440")
    if not (start < end):
        raise errors.invalid_request(
            "window_start_minute must be < window_end_minute")


# ===========================================================================
# Create / read / list
# ===========================================================================
@bp.route("/floral/orders", methods=["POST"])
def create_order():
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    body = get_body()
    require_fields(body, ["customer_id", "arrangement_id", "zone_id",
                          "delivery_date", "window_start_minute",
                          "window_end_minute"])
    customer_id = as_str(body, "customer_id")
    arrangement_id = as_str(body, "arrangement_id")
    zone_id = as_str(body, "zone_id")
    occasion = as_enum(body, "occasion", OCCASIONS, required=False, default="GENERAL")
    card_message = as_str(body, "card_message", required=False, default="")
    delivery_date = as_str(body, "delivery_date")
    window_start = as_int(body, "window_start_minute")
    window_end = as_int(body, "window_end_minute")
    apply_wallet_credit = as_bool(body, "apply_wallet_credit", default=False)

    # Ownership: a Customer may only draft for itself (owner FK is customer_id).
    if role == "Customer" and customer_id != user_id:
        raise errors.not_resource_owner("Customer may only draft own orders")

    # Existence: validate FKs left-to-right.
    if customer_id not in store.customers:
        raise errors.not_found("customer_id not found")
    if arrangement_id not in store.arrangements:
        raise errors.not_found("arrangement_id not found")
    if zone_id not in store.zones:
        raise errors.not_found("zone_id not found")

    # Schema-level field validation.
    clock.parse_date(delivery_date)
    if len(card_message) > 240:
        raise errors.invalid_request("card_message must be <= 240 chars")
    _validate_window(window_start, window_end)

    rec = make_record()
    rec.update({
        "customer_id": customer_id,
        "arrangement_id": arrangement_id,
        "zone_id": zone_id,
        "parent_recurrence_id": None,
        "source_order_id": None,
        "occasion": occasion,
        "card_message": card_message,
        "delivery_date": delivery_date,
        "window_start_minute": window_start,
        "window_end_minute": window_end,
        "apply_wallet_credit": apply_wallet_credit,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
        "estimated_total_cents": 0,
        "final_total_cents": 0,
        "wallet_credit_applied_cents": 0,
        "is_same_day": False,
        # internal: authorized amount snapshot
        "_authorized_amount_cents": 0,
    })
    store.orders[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/floral/orders/<oid>", methods=["GET"])
def get_order(oid):
    _, role = require_auth()
    require_role(role, {"Customer", "Dispatcher", "Florist", "CatalogAdmin"})
    rec = store.orders.get(oid)
    if rec is None:
        raise errors.not_found("Order not found")
    return success(public(rec))


@bp.route("/floral/orders", methods=["GET"])
def list_orders():
    _, role = require_auth()
    require_role(role, {"Customer", "Dispatcher", "Florist", "CatalogAdmin"})
    limit, offset = parse_pagination()
    rows = list(store.orders.values())
    for field in ("customer_id", "arrangement_id", "parent_recurrence_id",
                  "source_order_id", "zone_id"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r.get(field) == val]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


# ===========================================================================
# Quote: DRAFT -> QUOTED
# ===========================================================================
@bp.route("/floral/orders/<oid>/quote", methods=["POST"])
def quote_order(oid):
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    order = store.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found")
    _check_order_owner(order, user_id, role)

    # State precondition.
    if order["fulfillment_status"] != "DRAFT":
        raise errors.invalid_state("Quote is only defined from DRAFT")

    arrangement = store.arrangements[order["arrangement_id"]]
    zone = store.zones[order["zone_id"]]
    customer = store.customers[order["customer_id"]]

    # Active checks.
    if not arrangement["active"]:
        raise errors.ApiError(errors.ERR_ARRANGEMENT_INACTIVE, 409,
                              "Arrangement is inactive")
    if not zone["active"]:
        raise errors.ApiError(errors.ERR_ZONE_INACTIVE, 409, "Zone is inactive")

    cd = clock.clock_date()
    delivery_date = order["delivery_date"]
    # Same-day cutoff (priority 8) is evaluated BEFORE the past-date check
    # only by the §1.4 numbering; PRD §3.2 states the past-date rule is
    # checked then "the same-day rule is evaluated next" -> past first.
    # PRD ordering: delivery_date must not be strictly before clock date.
    if cd is not None:
        d_date = clock.parse_date(delivery_date)
        c_date = clock.parse_date(cd)
        if d_date < c_date:
            raise errors.ApiError(errors.ERR_DELIVERY_DATE_IN_PAST, 409,
                                  "delivery_date is in the past")

    is_same_day = (cd is not None and delivery_date == cd)
    if is_same_day:
        window = pricing.find_holiday_window(delivery_date)
        if window is not None:
            effective_cutoff = window["surge_cutoff_hour_utc"]
        else:
            effective_cutoff = zone["same_day_cutoff_hour_utc"]
        if clock.clock_hour() >= effective_cutoff:
            raise errors.ApiError(errors.ERR_PAST_SAME_DAY_CUTOFF, 409,
                                  "Past the effective same-day cutoff")

    # Compute estimate.
    quote = pricing.compute_quote_estimate(order, customer, arrangement, zone)
    pre_credit = quote["pre_credit"]

    if order["apply_wallet_credit"]:
        applied = min(customer["wallet_credit_cents"], pre_credit)
    else:
        applied = 0
    order["wallet_credit_applied_cents"] = applied
    if applied > 0:
        customer["wallet_credit_cents"] -= applied
        touch(customer)
    order["estimated_total_cents"] = pre_credit - applied
    order["is_same_day"] = is_same_day
    order["fulfillment_status"] = "QUOTED"
    touch(order)
    return success(public(order))


# ===========================================================================
# Authorize payment: UNPAID -> AUTHORIZED
# ===========================================================================
@bp.route("/floral/orders/<oid>/authorize-payment", methods=["POST"])
def authorize_payment(oid):
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    order = store.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found")
    _check_order_owner(order, user_id, role)
    if order["payment_status"] != "UNPAID":
        raise errors.invalid_state("Authorization is only defined from UNPAID")
    if order["fulfillment_status"] != "QUOTED":
        raise errors.precondition_not_met("Order must be QUOTED to authorize")
    order["_authorized_amount_cents"] = order["estimated_total_cents"]
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return success(public(order))


# ===========================================================================
# Book: QUOTED -> BOOKED (OCC + capacity + florist selection)
# ===========================================================================
@bp.route("/floral/orders/<oid>/book", methods=["POST"])
def book_order(oid):
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    order = store.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found")
    _check_order_owner(order, user_id, role)
    body = get_body()
    require_fields(body, ["expected_order_version"])
    expected_version = as_int(body, "expected_order_version")

    # State: only from QUOTED.
    if order["fulfillment_status"] != "QUOTED":
        raise errors.invalid_state("Book is only defined from QUOTED")
    # Cross-dimension precondition: payment AUTHORIZED.
    if order["payment_status"] != "AUTHORIZED":
        raise errors.precondition_not_met("Order payment must be AUTHORIZED")

    zone = store.zones[order["zone_id"]]

    # Zone window capacity (priority 11).
    existing = pricing.zone_window_bookings(
        order["zone_id"], order["delivery_date"],
        order["window_start_minute"], order["window_end_minute"])
    if existing >= zone["window_capacity_per_slot"]:
        raise errors.ApiError(errors.ERR_ZONE_WINDOW_FULL, 409,
                              "Zone window is full")

    # Florist selection (priority 12).
    florist = pricing.select_fulfilling_florist(order)
    if florist is None:
        raise errors.ApiError(errors.ERR_NO_FLORIST_AVAILABLE, 409,
                              "No florist available")

    # OCC (priority 13) is the last check.
    if expected_version != order["version"]:
        raise errors.stale_order_version("expected_order_version is stale")

    # Side effects: create DeliverySlot.
    slot = make_record(with_version=False)
    slot.update({
        "order_id": order["id"],
        "zone_id": order["zone_id"],
        "slot_date": order["delivery_date"],
        "slot_start_minute": order["window_start_minute"],
        "slot_end_minute": order["window_end_minute"],
        "released": False,
    })
    store.delivery_slots[slot["id"]] = slot

    # Create WireFulfillment.
    wf = make_record()
    wf.update({
        "order_id": order["id"],
        "florist_id": florist["id"],
        "assigned_delivery_date": order["delivery_date"],
        "status": "ASSIGNED",
        "florist_surcharge_cents": florist["wire_surcharge_cents"],
    })
    store.wire_fulfillments[wf["id"]] = wf

    order["fulfillment_status"] = "BOOKED"
    touch(order)
    return success(public(order))


# ===========================================================================
# Dispatch: BOOKED -> IN_TRANSIT (+ payment CAPTURED, final total)
# ===========================================================================
@bp.route("/floral/orders/<oid>/dispatch", methods=["POST"])
def dispatch_order(oid):
    _, role = require_auth()
    require_role(role, {"Florist", "Dispatcher"})
    order = store.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found")
    if order["fulfillment_status"] != "BOOKED":
        raise errors.invalid_state("Dispatch is only defined from BOOKED")
    wf = _wire_for_order(order["id"])
    if wf is None or wf["status"] != "ACCEPTED":
        raise errors.precondition_not_met("Wire fulfillment must be ACCEPTED")

    arrangement = store.arrangements[order["arrangement_id"]]
    zone = store.zones[order["zone_id"]]
    customer = store.customers[order["customer_id"]]
    subs = [s for s in store.substitutions.values()
            if s["order_id"] == order["id"]]
    final_total = pricing.compute_final_total(
        order, customer, arrangement, zone, wf, subs)
    order["final_total_cents"] = final_total
    order["fulfillment_status"] = "IN_TRANSIT"
    # Coupled payment capture: AUTHORIZED -> CAPTURED at final amount.
    if order["payment_status"] == "AUTHORIZED":
        order["payment_status"] = "CAPTURED"
    touch(order)
    return success(public(order))


# ===========================================================================
# Confirm delivery: IN_TRANSIT -> DELIVERED (+ loyalty)
# ===========================================================================
@bp.route("/floral/orders/<oid>/confirm-delivery", methods=["POST"])
def confirm_delivery(oid):
    _, role = require_auth()
    require_role(role, {"Florist", "Dispatcher"})
    order = store.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found")
    if order["fulfillment_status"] != "IN_TRANSIT":
        raise errors.invalid_state("Confirm is only defined from IN_TRANSIT")
    customer = store.customers[order["customer_id"]]
    customer["lifetime_delivered_count"] += 1
    pricing.promote_loyalty_tier(customer)
    touch(customer)
    order["fulfillment_status"] = "DELIVERED"
    touch(order)
    return success(public(order))


# ===========================================================================
# Cancel: DRAFT/QUOTED/BOOKED -> CANCELLED
# ===========================================================================
@bp.route("/floral/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = require_auth()
    require_role(role, {"Customer", "Dispatcher"})
    order = store.orders.get(oid)
    if order is None:
        raise errors.not_found("Order not found")
    _check_order_owner(order, user_id, role)
    if order["fulfillment_status"] not in {"DRAFT", "QUOTED", "BOOKED"}:
        raise errors.invalid_state("Cancel is not defined from this state")

    # Release delivery slot(s) for this order, if any.
    for slot in store.delivery_slots.values():
        if slot["order_id"] == order["id"] and not slot["released"]:
            slot["released"] = True

    # Release wire fulfillment(s) for this order, if any (decrement load).
    for wf in store.wire_fulfillments.values():
        if wf["order_id"] == order["id"] and wf["status"] != "RELEASED":
            wf["status"] = "RELEASED"
            touch(wf)

    # Refund applied wallet credit.
    applied = order.get("wallet_credit_applied_cents", 0)
    if applied > 0:
        customer = store.customers[order["customer_id"]]
        customer["wallet_credit_cents"] += applied
        touch(customer)

    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success(public(order))


# ===========================================================================
# Reverse-reachability reads
# ===========================================================================
def _wire_for_order(order_id):
    """The (current) WireFulfillment for an order, if one exists. Booking
    creates at most one live fulfillment per order at a time."""
    candidates = [wf for wf in store.wire_fulfillments.values()
                  if wf["order_id"] == order_id]
    if not candidates:
        return None
    # Prefer a non-released fulfillment; else the most recent.
    live = [wf for wf in candidates if wf["status"] != "RELEASED"]
    pool = live if live else candidates
    pool.sort(key=lambda r: r.get("_seq", 0))
    return pool[-1]


@bp.route("/floral/orders/<oid>/wire-fulfillments", methods=["GET"])
def order_wire_fulfillments(oid):
    _, role = require_auth()
    require_role(role, {"Customer", "Dispatcher", "Florist", "CatalogAdmin"})
    if oid not in store.orders:
        raise errors.not_found("Order not found")
    limit, offset = parse_pagination()
    rows = [wf for wf in store.wire_fulfillments.values()
            if wf["order_id"] == oid]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/floral/orders/<oid>/substitutions", methods=["GET"])
def order_substitutions(oid):
    _, role = require_auth()
    require_role(role, {"Customer", "Dispatcher", "Florist", "CatalogAdmin"})
    if oid not in store.orders:
        raise errors.not_found("Order not found")
    limit, offset = parse_pagination()
    rows = [s for s in store.substitutions.values() if s["order_id"] == oid]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/floral/orders/<oid>/delivery-slots", methods=["GET"])
def order_delivery_slots(oid):
    _, role = require_auth()
    require_role(role, {"Dispatcher", "CatalogAdmin"})
    if oid not in store.orders:
        raise errors.not_found("Order not found")
    limit, offset = parse_pagination()
    rows = [s for s in store.delivery_slots.values() if s["order_id"] == oid]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/floral/orders/<oid>/claims", methods=["GET"])
def order_claims(oid):
    _, role = require_auth()
    require_role(role, {"Customer", "Dispatcher", "CatalogAdmin"})
    if oid not in store.orders:
        raise errors.not_found("Order not found")
    limit, offset = parse_pagination()
    rows = [c for c in store.claims.values() if c["order_id"] == oid]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)
