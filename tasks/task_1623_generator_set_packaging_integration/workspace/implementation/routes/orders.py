"""PackageOrder endpoints: create, get, list, authorize, cancel."""

from flask import Blueprint

import db
import errors
import middleware as mw
import response as resp
import services.calculations as calc
import services.cascade as cascade

bp = Blueprint("orders", __name__)

VALID_LOCALES = {"US_CA", "US_TX", "DE"}
VALID_OCCUPANCY = {"STANDARD", "HOSPITAL"}
VALID_APPLICATION = {"STANDBY", "PRIME"}


@bp.route("/genset-packaging/orders", methods=["POST"])
def create_order():
    mw.require_roles("SalesEngineer")
    body = mw.get_json_body()

    customer_id = mw.require_string(body, "customer_id")
    site_locale = mw.require_enum(body, "site_locale", VALID_LOCALES)
    occupancy_type = mw.require_enum(body, "occupancy_type", VALID_OCCUPANCY)
    application = mw.require_enum(body, "application", VALID_APPLICATION)

    customer = db.customers.get(customer_id)
    if customer is None:
        raise errors.not_found("Customer account not found")

    record = {
        "customer_id": customer_id,
        "site_locale": site_locale,
        "occupancy_type": occupancy_type,
        "application": application,
        "build_status": "SPEC",
        "commercial_status": "QUOTE",
        "authorized_amount_cents": 0,
        "committed_amount_cents": 0,
        "refunded_amount_cents": 0,
        "restocking_fee_cents": 0,
        "freight_charge_cents": 0,
        "total_price_cents": 0,
        "discount_tier": "NONE",
    }
    db.stamp_new(record)
    db.orders[record["id"]] = record
    return resp.success_created(record)


@bp.route("/genset-packaging/orders/<orderId>", methods=["GET"])
def get_order(orderId):
    mw.authenticate()
    record = db.orders.get(orderId)
    if record is None:
        raise errors.not_found("Package order not found")
    return resp.success_object(record)


@bp.route("/genset-packaging/orders", methods=["GET"])
def list_orders():
    mw.authenticate()
    limit, offset = mw.parse_pagination()

    customer_id = mw.request.args.get("customer_id")
    items = list(db.orders.values())
    if customer_id:
        items = [o for o in items if o["customer_id"] == customer_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.success_list(page, limit, offset, total)


@bp.route("/genset-packaging/orders/<orderId>/authorize", methods=["POST"])
def authorize_order(orderId):
    mw.require_roles("SalesEngineer")
    body = mw.get_json_body()

    order = db.orders.get(orderId)
    if order is None:
        raise errors.not_found("Package order not found")

    amount_cents = mw.require_int(body, "amount_cents", minimum=0)
    freight_charge_cents = mw.require_int(body, "freight_charge_cents", minimum=0)

    # --- Priority 10 (referential): approved sizing study must exist ---
    has_approved = any(
        s["order_id"] == orderId and s["status"] == "APPROVED"
        for s in db.sizing_studies.values()
    )
    if not has_approved:
        raise errors.ApiError(
            errors.ERR_SIZING_NOT_APPROVED, 409,
            "At least one sizing study for this order must be APPROVED",
        )

    # --- Priority 10 (referential): customer must be ACTIVE ---
    customer = db.customers.get(order["customer_id"])
    if customer is None:
        raise errors.not_found("Customer account not found")
    if customer["status"] != "ACTIVE":
        raise errors.ApiError(
            errors.ERR_CUSTOMER_SUSPENDED, 409,
            "Customer account is SUSPENDED",
        )

    # --- Priority 11 (fiscal): credit check ---
    if customer["credit_utilized_cents"] + amount_cents > customer["credit_limit_cents"]:
        raise errors.ApiError(
            errors.ERR_CREDIT_LIMIT_EXCEEDED, 422,
            "Authorization would exceed customer credit limit",
        )

    # --- State check: commercial_status must be QUOTE ---
    if order["commercial_status"] != "QUOTE":
        raise errors.ApiError(
            errors.ERR_INVALID_COMMERCIAL_STATE, 409,
            "Order commercial_status must be QUOTE to authorize",
        )

    # Apply side effects
    order["commercial_status"] = "AUTHORIZED"
    order["authorized_amount_cents"] = amount_cents
    order["committed_amount_cents"] = amount_cents
    order["freight_charge_cents"] = freight_charge_cents
    db.touch(order)

    customer["credit_utilized_cents"] += amount_cents
    db.touch(customer)

    return resp.success_object(order)


@bp.route("/genset-packaging/orders/<orderId>/cancel", methods=["POST"])
def cancel_order(orderId):
    mw.require_roles("SalesEngineer")

    order = db.orders.get(orderId)
    if order is None:
        raise errors.not_found("Package order not found")

    # Gate: build_status must not be COMMISSIONED or CANCELLED
    if order["build_status"] in ("COMMISSIONED", "CANCELLED"):
        raise errors.ApiError(
            errors.ERR_INVALID_BUILD_STATE, 409,
            "Cannot cancel an order that is COMMISSIONED or CANCELLED",
        )

    build_status_at_cancel = order["build_status"]

    # --- Hop 1: cancel every non-terminal configuration ---
    for config in list(db.configurations.values()):
        if config["order_id"] == orderId and config["status"] in ("DRAFT", "LOCKED", "RELEASED"):
            cascade.cancel_configuration(config)

    # --- Release BOOKED shipments, restore crane occupancy ---
    cascade.release_booked_shipments_for_order(orderId)

    # --- Cancel open commissioning events ---
    for event in db.commissioning_events.values():
        if event["order_id"] == orderId and event["status"] in ("REQUESTED", "ASSIGNED", "IN_PROGRESS"):
            event["status"] = "CANCELLED"
            db.touch(event)

    # --- Cancel open service contracts ---
    for contract in db.service_contracts.values():
        if contract["order_id"] == orderId and contract["status"] in ("QUOTED", "BOUND"):
            contract["status"] = "CANCELLED"
            db.touch(contract)

    # --- Refund if commercially committed ---
    if order["commercial_status"] in ("AUTHORIZED", "INVOICED"):
        fee, refund = calc.compute_restocking_refund(
            build_status_at_cancel, order["committed_amount_cents"]
        )
        customer = db.customers.get(order["customer_id"])
        if customer is not None:
            customer["credit_utilized_cents"] -= order["committed_amount_cents"]
            db.touch(customer)
        order["restocking_fee_cents"] = fee
        order["refunded_amount_cents"] = refund
        order["committed_amount_cents"] = 0
        order["commercial_status"] = "REFUNDED"

    order["build_status"] = "CANCELLED"
    db.touch(order)

    return resp.success_object(order)
