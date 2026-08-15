"""Charter quote endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, touch, require_fields, get_str, get_bool, get_int, get_float,
    get_enum, get_datetime,
)
from services.pricing import (
    calc_quote_pricing, calc_deposit_tier, compute_requires_overnight, compute_requires_relief_driver,
)
from services.serializers import quote_view, order_view

bp = Blueprint("quotes", __name__)


VEHICLE_CLASSES = ("STANDARD", "PREMIUM", "EXECUTIVE")


def lazy_quote_expiry(q: dict):
    """QUOTED -> EXPIRED if now >= quote_expiry."""
    if q.get("status") == "QUOTED" and q.get("quote_expiry"):
        expiry = db.parse_iso(q["quote_expiry"])
        if db.now_utc() >= expiry:
            q["status"] = "EXPIRED"
            touch(q)


@bp.route("/api/v1/quotes", methods=["POST"])
def create_quote():
    require_roles("QuoteAgent")
    payload = request.get_json(silent=True) or {}
    require_fields(
        payload,
        "customer_id", "trip_date", "return_date", "origin", "destination",
        "passenger_count", "estimated_miles", "estimated_hours",
    )
    customer_id = get_str(payload, "customer_id", required=True)
    customer = db.customers.get(customer_id)
    if customer is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "customer not found")

    trip_date = get_datetime(payload, "trip_date", required=True)
    return_date = get_datetime(payload, "return_date", required=True)
    origin = get_str(payload, "origin", required=True)
    destination = get_str(payload, "destination", required=True)
    passenger_count = get_int(payload, "passenger_count", required=True)
    estimated_miles = get_int(payload, "estimated_miles", required=True)
    estimated_hours = get_float(payload, "estimated_hours", required=True)
    ada_required = get_bool(payload, "ada_required", default=False)
    vehicle_class_requested = get_enum(payload, "vehicle_class_requested", VEHICLE_CLASSES, default="STANDARD")
    special_requests = get_str(payload, "special_requests", default="", allow_empty=True) or ""

    now = db.iso_now()
    qid = db.new_id()
    q = {
        "id": qid,
        "customer_id": customer_id,
        "trip_date": db.to_iso(trip_date),
        "return_date": db.to_iso(return_date),
        "origin": origin,
        "destination": destination,
        "passenger_count": passenger_count,
        "estimated_miles": estimated_miles,
        "estimated_hours": estimated_hours,
        "requires_overnight": False,
        "requires_relief_driver": False,
        "ada_required": ada_required,
        "vehicle_class_requested": vehicle_class_requested,
        "status": "DRAFT",
        "mileage_rate_cents": None,
        "hourly_rate_cents": None,
        "overnight_fee_cents": None,
        "relief_driver_fee_cents": None,
        "subtotal_cents": None,
        "tax_cents": None,
        "total_cents": None,
        "deposit_cents": None,
        "quote_expiry": None,
        "pricing_variant": None,
        "special_requests": special_requests,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.quotes[qid] = q
    return success_object(quote_view(q), status=201)


@bp.route("/api/v1/quotes", methods=["GET"])
def list_quotes():
    user_id, role = require_roles("QuoteAgent", "DispatchManager", "PlatformAdmin", "Customer")
    limit, offset = get_pagination()
    status = request.args.get("status")
    customer_id = request.args.get("customer_id")
    items = sorted(db.quotes.values(), key=lambda x: x["created_at"])
    for q in items:
        lazy_quote_expiry(q)
    if role == "Customer":
        items = [q for q in items if q.get("customer_id") == user_id]
    if status:
        items = [q for q in items if q.get("status") == status]
    if customer_id:
        items = [q for q in items if q.get("customer_id") == customer_id]
    page, total = paginate(items, limit, offset)
    return success_list([quote_view(q) for q in page], limit, offset, total)


@bp.route("/api/v1/quotes/<qid>", methods=["GET"])
def get_quote(qid):
    user_id, role = require_roles("QuoteAgent", "DispatchManager", "Customer")
    q = db.quotes.get(qid)
    if q is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")
    if role == "Customer" and q.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only access own resources")
    lazy_quote_expiry(q)
    return success_object(quote_view(q))


@bp.route("/api/v1/quotes/<qid>/price", methods=["POST"])
def price_quote(qid):
    require_roles("QuoteAgent")
    q = db.quotes.get(qid)
    if q is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")
    if q["status"] != "DRAFT":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"quote is in state {q['status']}, cannot price")

    customer = db.customers.get(q["customer_id"])
    if customer is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "customer not found")
    if customer.get("credit_status") == "COLLECTIONS":
        raise errors.make_error(errors.ERR_CREDIT_SUSPENDED, "customer credit status is COLLECTIONS")

    if q.get("estimated_miles", 0) <= 0 or q.get("estimated_hours", 0) <= 0 or q.get("passenger_count", 0) <= 0:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "estimated_miles, estimated_hours, and passenger_count must all be positive")

    # Compute flags
    trip_date = db.parse_iso(q["trip_date"])
    return_date = db.parse_iso(q["return_date"])
    q["requires_overnight"] = compute_requires_overnight(q["estimated_hours"], trip_date, return_date)
    q["requires_relief_driver"] = compute_requires_relief_driver(q["estimated_hours"])

    # Pricing
    pricing = calc_quote_pricing(q, customer)
    q.update(pricing)

    # Deposit at pricing time
    now = db.now_utc()
    q["deposit_cents"] = calc_deposit_tier(q["total_cents"], trip_date, now)

    q["quote_expiry"] = db.to_iso(now + timedelta(hours=72))
    q["status"] = "QUOTED"
    touch(q)
    return success_object(quote_view(q))


@bp.route("/api/v1/quotes/<qid>/accept", methods=["POST"])
def accept_quote(qid):
    user_id, role = require_roles("Customer")
    q = db.quotes.get(qid)
    if q is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")
    if q.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only accept own quotes")
    if q["status"] != "QUOTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"quote is in state {q['status']}, cannot accept")

    # Lazy expiry check: if expired by now, return ERR_INVALID_STATE? No - spec says ERR_QUOTE_EXPIRED
    now = db.now_utc()
    expiry = db.parse_iso(q["quote_expiry"]) if q.get("quote_expiry") else None
    if expiry is not None and now >= expiry:
        raise errors.make_error(errors.ERR_QUOTE_EXPIRED, "quote has expired")

    customer = db.customers.get(q["customer_id"])
    if customer is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "customer not found")
    if customer.get("credit_status") == "COLLECTIONS":
        raise errors.make_error(errors.ERR_CREDIT_SUSPENDED, "customer credit status is COLLECTIONS")

    payload = request.get_json(silent=True) or {}
    expected_version = payload.get("expected_quote_version")
    if expected_version is None:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "expected_quote_version is required")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "expected_quote_version must be an integer")
    if expected_version != q["version"]:
        raise errors.make_error(errors.ERR_STALE_VERSION, "quote version mismatch")

    # Compute deposit at acceptance time
    trip_date = db.parse_iso(q["trip_date"])
    deposit_cents = calc_deposit_tier(q["total_cents"], trip_date, now)

    # Create order
    oid = db.new_id()
    order = {
        "id": oid,
        "quote_id": qid,
        "customer_id": q["customer_id"],
        "status": "PENDING_DEPOSIT",
        "assigned_vehicle_id": None,
        "assigned_driver_id": None,
        "relief_driver_id": None,
        "actual_miles": None,
        "actual_hours": None,
        "extra_hours": 0.0,
        "extra_hours_charge_cents": 0,
        "fuel_surcharge_cents": 0,
        "deposit_cents": deposit_cents,
        "deposit_paid_cents": 0,
        "deposit_paid_at": None,
        "cancellation_fee_cents": 0,
        "refund_cents": 0,
        "final_subtotal_cents": None,
        "final_tax_cents": None,
        "final_invoice_cents": None,
        "balance_due_cents": None,
        "itinerary_changes": [],
        "cancelled_by": None,
        "cancellation_reason": None,
        "completed_at": None,
        "created_at": db.iso_now(),
        "updated_at": db.iso_now(),
        "version": 1,
    }
    db.orders[oid] = order

    q["status"] = "ACCEPTED"
    touch(q)

    return success_object(order_view(order), status=201)


@bp.route("/api/v1/quotes/<qid>/cancel", methods=["POST"])
def cancel_quote(qid):
    user_id, role = require_roles("Customer", "QuoteAgent")
    q = db.quotes.get(qid)
    if q is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")
    if role == "Customer" and q.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only cancel own quotes")
    if q["status"] not in ("DRAFT", "QUOTED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, f"quote is in state {q['status']}, cannot cancel")
    q["status"] = "CANCELLED"
    touch(q)
    return success_object(quote_view(q))


@bp.route("/api/v1/quotes/<qid>/check-expiry", methods=["POST"])
def check_expiry(qid):
    require_roles("QuoteAgent", "DispatchManager")
    q = db.quotes.get(qid)
    if q is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")
    lazy_quote_expiry(q)
    return success_object(quote_view(q))


@bp.route("/api/v1/quotes/<qid>/orders", methods=["GET"])
def list_quote_orders(qid):
    user_id, role = require_roles("QuoteAgent", "DispatchManager", "Customer")
    q = db.quotes.get(qid)
    if q is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")
    if role == "Customer" and q.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only access own resources")
    limit, offset = get_pagination()
    items = sorted([o for o in db.orders.values() if o.get("quote_id") == qid], key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return success_list([order_view(o) for o in page], limit, offset, total)
