"""RentalOrder endpoints (PRD sections 3.3, 3.5, 3.7, 3.8)."""
from flask import Blueprint, request

from db import db
from errors import err
from helpers import (
    get_order, get_account, get_container, get_container_type,
    check_order_owner, paginate, current_date,
)
from middleware import require_auth, require_role
from response import success
import serialize
from serialize import (
    rental_order as ser, account_outstanding_cents, route_stop_count,
)
import validate

bp = Blueprint("rental_orders", __name__)


@bp.post("/rental-orders")
def book_order():
    user_id, role = require_auth()
    require_role(role, ["Contractor", "Dispatcher"])
    body = validate.get_json_body()
    validate.require_fields(body, [
        "account_id", "container_type_id", "site_address", "requested_delivery_date",
    ])
    account_id = validate.require_string(body, "account_id")
    container_type_id = validate.require_string(body, "container_type_id")
    site_address = validate.require_string(body, "site_address")
    requested_delivery_date = validate.require_date(body, "requested_delivery_date")
    requires_street_permit = validate.require_bool(body, "requires_street_permit", default=False)

    # existence of FK ids (priority 3, left to right).
    account = get_account(account_id)
    ctype = get_container_type(container_type_id)

    # ownership (priority 4): a contractor booking must book for itself.
    if role == "Contractor" and account_id != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Contractor may only book for its own account")

    # account standing (state): must be ACTIVE.
    if account["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_SUSPENDED", "Account is suspended")

    # credit gate (projected reading): base_rate_cents <= available_credit_cents.
    outstanding = account_outstanding_cents(account_id)
    available = account["credit_limit_cents"] - outstanding
    if ctype["base_rate_cents"] > available:
        raise err("ERR_CREDIT_LIMIT_EXCEEDED", "Order base rate exceeds available credit")

    rec = db.insert_with_common(db.rental_orders, {
        "account_id": account_id,
        "container_type_id": container_type_id,
        "container_id": None,
        "site_address": site_address,
        "requested_delivery_date": requested_delivery_date,
        "delivered_on": None,
        "picked_up_on": None,
        "rental_days": 0,
        "requires_street_permit": requires_street_permit,
        "logistics_status": "BOOKED",
        "billing_status": "UNBILLED",
        "estimated_total_cents": 0,
        "final_total_cents": 0,
    })

    # side effect: a DELIVERY ServiceStop is created UNASSIGNED for the order.
    db.insert_with_common(db.service_stops, {
        "order_id": rec["id"],
        "route_id": None,
        "stop_type": "DELIVERY",
        "sequence": None,
        "estimated_weight_lbs": 0,
        "status": "UNASSIGNED",
    })
    return success(ser(rec), status=201)


@bp.get("/rental-orders")
def list_orders():
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "BillingClerk", "Contractor"])
    limit, offset = validate.get_pagination()
    records = list(db.rental_orders.values())
    if role == "Contractor":
        records = [r for r in records if r["account_id"] == user_id]
    account_id = request.args.get("account_id")
    container_type_id = request.args.get("container_type_id")
    container_id = request.args.get("container_id")
    logistics_status = request.args.get("logistics_status")
    billing_status = request.args.get("billing_status")
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if container_type_id is not None:
        records = [r for r in records if r["container_type_id"] == container_type_id]
    if container_id is not None:
        records = [r for r in records if r["container_id"] == container_id]
    if logistics_status is not None:
        records = [r for r in records if r["logistics_status"] == logistics_status]
    if billing_status is not None:
        records = [r for r in records if r["billing_status"] == billing_status]
    return paginate(records, ser, limit, offset)


@bp.get("/rental-orders/<order_id>")
def get_order_ep(order_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "BillingClerk", "Contractor"])
    order = get_order(order_id)
    check_order_owner(order, role, user_id)
    return success(ser(order), status=200)


@bp.get("/rental-orders/<order_id>/service-stops")
def list_order_stops(order_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "Contractor"])
    order = get_order(order_id)
    check_order_owner(order, role, user_id)
    limit, offset = validate.get_pagination()
    records = [s for s in db.service_stops.values() if s["order_id"] == order_id]
    return paginate(records, serialize.service_stop, limit, offset)


@bp.get("/rental-orders/<order_id>/weigh-tickets")
def list_order_tickets(order_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "BillingClerk", "ScaleOperator", "Contractor"])
    order = get_order(order_id)
    check_order_owner(order, role, user_id)
    limit, offset = validate.get_pagination()
    records = [t for t in db.weigh_tickets.values() if t["order_id"] == order_id]
    return paginate(records, serialize.weigh_ticket, limit, offset)


@bp.get("/rental-orders/<order_id>/street-permits")
def list_order_permits(order_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "PermitOfficer", "Contractor"])
    order = get_order(order_id)
    check_order_owner(order, role, user_id)
    limit, offset = validate.get_pagination()
    records = [p for p in db.street_permits.values() if p["order_id"] == order_id]
    return paginate(records, serialize.street_permit, limit, offset)


@bp.get("/rental-orders/<order_id>/invoice")
def list_order_invoice(order_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "Dispatcher", "BillingClerk", "Contractor"])
    order = get_order(order_id)
    check_order_owner(order, role, user_id)
    limit, offset = validate.get_pagination()
    records = [i for i in db.invoices.values() if i["order_id"] == order_id]
    return paginate(records, serialize.invoice, limit, offset)


@bp.post("/rental-orders/<order_id>/swap-stop")
def create_swap_stop(order_id):
    user_id, role = require_auth()
    require_role(role, ["Dispatcher", "Contractor"])
    order = get_order(order_id)
    check_order_owner(order, role, user_id)
    body = validate.get_json_body()
    estimated_weight_lbs = validate.optional_non_negative_int(body, "estimated_weight_lbs", 0)
    if order["logistics_status"] != "ON_SITE":
        raise err("ERR_ORDER_NOT_ON_SITE", "Order is not ON_SITE")
    rec = db.insert_with_common(db.service_stops, {
        "order_id": order_id,
        "route_id": None,
        "stop_type": "SWAP",
        "sequence": None,
        "estimated_weight_lbs": estimated_weight_lbs,
        "status": "UNASSIGNED",
    })
    return success(serialize.service_stop(rec), status=201)


@bp.post("/rental-orders/<order_id>/pickup-stop")
def create_pickup_stop(order_id):
    user_id, role = require_auth()
    require_role(role, ["Dispatcher", "Contractor"])
    order = get_order(order_id)
    check_order_owner(order, role, user_id)
    body = validate.get_json_body()
    estimated_weight_lbs = validate.optional_non_negative_int(body, "estimated_weight_lbs", 0)
    if order["logistics_status"] != "ON_SITE":
        raise err("ERR_ORDER_NOT_ON_SITE", "Order is not ON_SITE")
    rec = db.insert_with_common(db.service_stops, {
        "order_id": order_id,
        "route_id": None,
        "stop_type": "PICKUP",
        "sequence": None,
        "estimated_weight_lbs": estimated_weight_lbs,
        "status": "UNASSIGNED",
    })
    return success(serialize.service_stop(rec), status=201)


@bp.post("/rental-orders/<order_id>/dispatch-delivery")
def dispatch_delivery(order_id):
    _, role = require_auth()
    require_role(role, ["Dispatcher"])
    order = get_order(order_id)
    body = validate.get_json_body()
    validate.require_fields(body, ["container_id", "expected_container_version"])
    container_id = validate.require_string(body, "container_id")
    expected_version = body.get("expected_container_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err("ERR_INVALID_REQUEST", "expected_container_version must be an integer")

    # existence of body id (priority 3).
    container = get_container(container_id)

    # state (priority 5): order BOOKED.
    if order["logistics_status"] != "BOOKED":
        raise err("ERR_ORDER_NOT_BOOKED", "Order is not BOOKED")
    # account ACTIVE.
    account = db.contractor_accounts.get(order["account_id"])
    if account is None or account["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_SUSPENDED", "Account is suspended")
    # container IN_YARD.
    if container["status"] != "IN_YARD":
        raise err("ERR_CONTAINER_NOT_AVAILABLE", "Container is not IN_YARD")
    # container type match (priority 6).
    if container["container_type_id"] != order["container_type_id"]:
        raise err("ERR_CONTAINER_TYPE_MISMATCH", "Container type does not match order")
    # permit requirement (priority 7).
    if order["requires_street_permit"]:
        covered = False
        for p in db.street_permits.values():
            if (p["order_id"] == order_id and p["status"] == "APPROVED"
                    and p["valid_from"] <= order["requested_delivery_date"] <= p["valid_until"]):
                covered = True
                break
        if not covered:
            raise err("ERR_PERMIT_NOT_APPROVED",
                      "No approved permit covers the requested delivery date")
    # OCC (priority: stale container version).
    if expected_version != container["version"]:
        raise err("ERR_STALE_CONTAINER_VERSION", "Container version is stale")

    # Apply.
    order["logistics_status"] = "SCHEDULED"
    order["container_id"] = container_id
    db.touch(order)
    container["status"] = "ASSIGNED"
    container["current_order_id"] = order_id
    db.touch(container)
    return success(ser(order), status=200)


@bp.post("/rental-orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = require_auth()
    require_role(role, ["Contractor", "Dispatcher"])
    order = get_order(order_id)
    check_order_owner(order, role, user_id)
    status = order["logistics_status"]
    if status not in ("BOOKED", "SCHEDULED"):
        raise err("ERR_ORDER_NOT_CANCELLABLE", "Order is not cancellable")

    order["logistics_status"] = "CANCELLED"
    db.touch(order)

    # Cascade to stops.
    for s in db.service_stops.values():
        if s["order_id"] != order_id:
            continue
        if s["status"] == "UNASSIGNED":
            s["status"] = "CANCELLED"
            db.touch(s)
        elif s["status"] == "ASSIGNED":
            # On a SCHEDULED order the DELIVERY stop is ASSIGNED on a PLANNING route.
            route = db.routes.get(s["route_id"]) if s["route_id"] else None
            s["status"] = "CANCELLED"
            db.touch(s)
            if route is not None:
                db.touch(route)  # stop_count recomputed (computed on read), version bumps

    # Release any committed container directly to the yard.
    if order["container_id"]:
        container = db.containers.get(order["container_id"])
        if container is not None:
            container["status"] = "IN_YARD"
            container["current_order_id"] = None
            db.touch(container)
        order["container_id"] = None
        db.touch(order)

    return success(ser(order), status=200)
