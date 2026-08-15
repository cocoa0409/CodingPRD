"""Charter order endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from services.helpers import (
    get_pagination, paginate, touch, get_str, get_int, get_float,
)
from services.pricing import (
    calc_cancellation_fee, calc_fuel_surcharge, calc_hos_feasibility,
    round_half_up_cents, MAINTENANCE_INTERVAL_MILES,
)
from services.safety import recalc_customer_safety_audit_score, recalc_driver_safety_score
from services.serializers import order_view

bp = Blueprint("orders", __name__)


@bp.route("/api/v1/orders", methods=["GET"])
def list_orders():
    user_id, role = require_roles("QuoteAgent", "DispatchManager", "PlatformAdmin", "Customer")
    limit, offset = get_pagination()
    status = request.args.get("status")
    customer_id = request.args.get("customer_id")
    quote_id = request.args.get("quote_id")
    assigned_vehicle_id = request.args.get("assigned_vehicle_id")
    assigned_driver_id = request.args.get("assigned_driver_id")
    relief_driver_id = request.args.get("relief_driver_id")

    items = sorted(db.orders.values(), key=lambda x: x["created_at"])
    if role == "Customer":
        items = [o for o in items if o.get("customer_id") == user_id]
    if status:
        items = [o for o in items if o.get("status") == status]
    if customer_id:
        items = [o for o in items if o.get("customer_id") == customer_id]
    if quote_id:
        items = [o for o in items if o.get("quote_id") == quote_id]
    if assigned_vehicle_id:
        items = [o for o in items if o.get("assigned_vehicle_id") == assigned_vehicle_id]
    if assigned_driver_id:
        items = [o for o in items if o.get("assigned_driver_id") == assigned_driver_id]
    if relief_driver_id:
        items = [o for o in items if o.get("relief_driver_id") == relief_driver_id]
    page, total = paginate(items, limit, offset)
    return success_list([order_view(o) for o in page], limit, offset, total)


@bp.route("/api/v1/orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = require_roles("QuoteAgent", "DispatchManager", "PlatformAdmin", "Customer")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if role == "Customer" and o.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only access own resources")
    return success_object(order_view(o))


@bp.route("/api/v1/orders/<oid>/pay-deposit", methods=["POST"])
def pay_deposit(oid):
    user_id, role = require_roles("Customer")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if o.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only pay own orders")
    if o["status"] != "PENDING_DEPOSIT":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"order is in state {o['status']}, cannot pay deposit")

    payload = request.get_json(silent=True) or {}
    amount_cents = payload.get("amount_cents")
    if amount_cents is None:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "amount_cents is required")
    if isinstance(amount_cents, bool) or not isinstance(amount_cents, int):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "amount_cents must be an integer")
    if amount_cents < o.get("deposit_cents", 0):
        raise errors.make_error(errors.ERR_INSUFFICIENT_DEPOSIT, "deposit amount is less than the required deposit")

    o["deposit_paid_cents"] = amount_cents
    o["deposit_paid_at"] = db.iso_now()
    o["status"] = "CONFIRMED"
    touch(o)

    # Update customer lifetime revenue
    customer = db.customers.get(o["customer_id"])
    if customer:
        customer["lifetime_revenue_cents"] = customer.get("lifetime_revenue_cents", 0) + amount_cents
        touch(customer)

    return success_object(order_view(o))


def _check_driver_eligibility(driver, quote):
    """Returns error or None. Caller wraps in proper error types."""
    if driver.get("cdl_class") not in ("CLASS_A", "CLASS_B"):
        return "ERR_CDL_INSUFFICIENT"
    endorsements = driver.get("endorsements", []) or []
    if "P" not in endorsements:
        return "ERR_CDL_INSUFFICIENT"
    if float(driver.get("safety_score", 100.0)) < 50.0:
        return "ERR_DRIVER_SAFETY_SCORE_LOW"
    return None


@bp.route("/api/v1/orders/<oid>/assign", methods=["POST"])
def assign_order(oid):
    require_roles("DispatchManager")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if o["status"] != "CONFIRMED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"order is in state {o['status']}, cannot assign")

    quote = db.quotes.get(o["quote_id"])
    if quote is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")

    payload = request.get_json(silent=True) or {}
    vehicle_id = payload.get("vehicle_id")
    driver_id = payload.get("driver_id")
    relief_driver_id = payload.get("relief_driver_id")
    expected_order_version = payload.get("expected_order_version")

    # Validate IDs exist
    if not vehicle_id:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "vehicle_id is required")
    if not driver_id:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "driver_id is required")
    vehicle = db.vehicles.get(vehicle_id)
    driver = db.drivers.get(driver_id)
    relief_driver = db.drivers.get(relief_driver_id) if relief_driver_id else None
    if vehicle is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "vehicle not found")
    if driver is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "driver not found")
    if relief_driver_id and relief_driver is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "relief driver not found")

    # State checks
    if vehicle.get("status") != "AVAILABLE":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"vehicle is in state {vehicle['status']}")
    if driver.get("status") != "AVAILABLE":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"driver is in state {driver['status']}")
    if relief_driver and relief_driver.get("status") != "AVAILABLE":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"relief driver is in state {relief_driver['status']}")

    trip_date = db.parse_iso(quote["trip_date"])
    now = db.now_utc()

    # HOS feasibility (priority 5)
    requires_relief = quote.get("requires_relief_driver", False)
    ok, hos_err = calc_hos_feasibility(driver, float(quote["estimated_hours"]), requires_relief)
    if not ok:
        raise errors.make_error(
            (hos_err, 422),
            f"HOS violation: {hos_err}",
        )

    # Inspection (priority 6)
    if db.parse_iso(vehicle["dot_inspection_expiry"]) <= trip_date:
        raise errors.make_error(errors.ERR_INSPECTION_EXPIRED, "vehicle DOT inspection expired")

    # Insurance (priority 7)
    if db.parse_iso(vehicle["insurance_expiry"]) <= trip_date:
        raise errors.make_error(errors.ERR_INSURANCE_EXPIRED, "vehicle insurance expired")

    # Driver safety score (priority 8)
    if float(driver.get("safety_score", 100.0)) < 50.0:
        raise errors.make_error(errors.ERR_DRIVER_SAFETY_SCORE_LOW, "driver safety score too low")

    # Capacity (priority 9)
    if vehicle.get("seating_capacity", 0) < quote.get("passenger_count", 0):
        raise errors.make_error(errors.ERR_CAPACITY_EXCEEDED, "vehicle capacity insufficient")

    # ADA (priority 10)
    if quote.get("ada_required") and not vehicle.get("ada_accessible"):
        raise errors.make_error(errors.ERR_ADA_REQUIRED, "vehicle does not have ADA lift")

    # Maintenance due (priority 11)
    if vehicle.get("odometer_miles", 0) >= vehicle.get("maintenance_due_miles", 0):
        raise errors.make_error(errors.ERR_MAINTENANCE_DUE, "vehicle is due for maintenance")

    # CDL (priority 12)
    if driver.get("cdl_class") not in ("CLASS_A", "CLASS_B"):
        raise errors.make_error(errors.ERR_CDL_INSUFFICIENT, "driver CDL class insufficient")
    if "P" not in (driver.get("endorsements") or []):
        raise errors.make_error(errors.ERR_CDL_INSUFFICIENT, "driver lacks P endorsement")

    # Relief driver eligibility
    if requires_relief:
        if not relief_driver_id:
            raise errors.make_error(errors.ERR_INVALID_REQUEST, "relief_driver_id is required for this quote")
        err = _check_driver_eligibility(relief_driver, quote)
        if err == "ERR_CDL_INSUFFICIENT":
            raise errors.make_error(errors.ERR_CDL_INSUFFICIENT, "relief driver CDL insufficient")
        if err == "ERR_DRIVER_SAFETY_SCORE_LOW":
            raise errors.make_error(errors.ERR_DRIVER_SAFETY_SCORE_LOW, "relief driver safety score too low")

    # OCC (priority 18)
    if expected_order_version is not None:
        if not isinstance(expected_order_version, int) or isinstance(expected_order_version, bool):
            raise errors.make_error(errors.ERR_INVALID_REQUEST, "expected_order_version must be an integer")
        if expected_order_version != o["version"]:
            raise errors.make_error(errors.ERR_STALE_VERSION, "order version mismatch")

    # Commit
    o["assigned_vehicle_id"] = vehicle_id
    o["assigned_driver_id"] = driver_id
    if relief_driver_id:
        o["relief_driver_id"] = relief_driver_id
    o["status"] = "ASSIGNED"
    touch(o)

    vehicle["status"] = "ASSIGNED"
    touch(vehicle)

    driver["status"] = "ON_DUTY_NOT_DRIVING"
    touch(driver)

    if relief_driver:
        relief_driver["status"] = "ON_DUTY_NOT_DRIVING"
        touch(relief_driver)

    return success_object(order_view(o))


@bp.route("/api/v1/orders/<oid>/start-trip", methods=["POST"])
def start_trip(oid):
    require_roles("DispatchManager")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if o["status"] != "ASSIGNED":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"order is in state {o['status']}, cannot start trip")

    quote = db.quotes.get(o["quote_id"])
    trip_date = db.parse_iso(quote["trip_date"])
    now = db.now_utc()
    if now < trip_date - timedelta(hours=1):
        raise errors.make_error(errors.ERR_TRIP_NOT_YET, "trip cannot be started more than 1 hour before scheduled departure")

    o["status"] = "IN_PROGRESS"
    touch(o)

    vehicle = db.vehicles.get(o["assigned_vehicle_id"])
    if vehicle:
        vehicle["status"] = "IN_TRIP"
        touch(vehicle)

    driver = db.drivers.get(o["assigned_driver_id"])
    if driver:
        driver["status"] = "ON_TRIP"
        touch(driver)

    if o.get("relief_driver_id"):
        relief = db.drivers.get(o["relief_driver_id"])
        if relief:
            relief["status"] = "ON_TRIP"
            touch(relief)

    return success_object(order_view(o))


def _complete_trip(o, quote):
    """Shared logic for completing a trip from IN_PROGRESS or DISPUTED."""
    payload = request.get_json(silent=True) or {}
    actual_miles = payload.get("actual_miles")
    actual_hours = payload.get("actual_hours")
    if actual_miles is None or isinstance(actual_miles, bool) or not isinstance(actual_miles, int):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "actual_miles is required and must be an integer")
    if actual_hours is None or isinstance(actual_hours, bool) or not isinstance(actual_hours, (int, float)):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "actual_hours is required and must be a number")
    if actual_miles <= 0:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "actual_miles must be positive")
    if float(actual_hours) <= 0:
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "actual_hours must be positive")
    actual_hours = float(actual_hours)

    customer = db.customers.get(o["customer_id"])

    o["actual_miles"] = actual_miles
    o["actual_hours"] = actual_hours

    # Extra hours
    estimated_hours = float(quote.get("estimated_hours", 0))
    extra_hours = max(0.0, actual_hours - estimated_hours)
    o["extra_hours"] = round(extra_hours, 1)
    hourly_rate = quote.get("hourly_rate_cents") or 0
    o["extra_hours_charge_cents"] = round_half_up_cents(Decimal(str(extra_hours)) * Decimal(hourly_rate) * Decimal("1.5"))

    # Fuel surcharge
    o["fuel_surcharge_cents"] = calc_fuel_surcharge(actual_miles, quote.get("subtotal_cents") or 0)

    # Final settlement - account for any breakdown compensation credits
    breakdown_credit = sum(
        (b.get("customer_compensation_cents") or 0)
        for b in db.breakdowns.values()
        if b.get("order_id") == o["id"] and b.get("status") in ("REPLACED", "RESOLVED_IN_PLACE")
    )
    final_subtotal = (quote.get("subtotal_cents") or 0) + o["extra_hours_charge_cents"] + o["fuel_surcharge_cents"] - breakdown_credit
    o["final_subtotal_cents"] = final_subtotal

    if customer and customer.get("tax_exempt"):
        o["final_tax_cents"] = 0
    else:
        o["final_tax_cents"] = round_half_up_cents(Decimal(final_subtotal) * Decimal("0.0825"))
    o["final_invoice_cents"] = final_subtotal + o["final_tax_cents"]
    o["balance_due_cents"] = o["final_invoice_cents"] - o.get("deposit_paid_cents", 0)

    now = db.now_utc()
    o["completed_at"] = now
    o["status"] = "COMPLETED"
    touch(o)

    # Vehicle cascade
    vehicle = db.vehicles.get(o.get("assigned_vehicle_id"))
    if vehicle:
        vehicle["odometer_miles"] = vehicle.get("odometer_miles", 0) + actual_miles
        if vehicle["odometer_miles"] >= vehicle.get("maintenance_due_miles", 0):
            vehicle["status"] = "IN_MAINTENANCE"
            # Schedule a preventive maintenance record
            mid = db.new_id()
            m = {
                "id": mid,
                "vehicle_id": vehicle["id"],
                "maintenance_type": "PREVENTIVE",
                "status": "SCHEDULED",
                "scheduled_date": db.iso_now(),
                "completed_date": None,
                "odometer_at_service": vehicle["odometer_miles"],
                "description": "Auto-scheduled preventive maintenance",
                "technician": "",
                "cost_cents": 0,
                "next_due_miles": vehicle["odometer_miles"] + MAINTENANCE_INTERVAL_MILES,
                "dot_inspection_passed": None,
                "defects_found": [],
                "created_at": db.iso_now(),
            }
            db.maintenance_records[mid] = m
        else:
            vehicle["status"] = "AVAILABLE"
        touch(vehicle)

    # Drivers cascade
    for did_field in ("assigned_driver_id", "relief_driver_id"):
        did = o.get(did_field)
        if not did:
            continue
        driver = db.drivers.get(did)
        if not driver:
            continue
        driver["status"] = "OFF_DUTY"
        driver["last_rest_start"] = db.iso_now()
        # HOS accumulators were already fed when the order's trip-log segments
        # were posted (PRD §3.5); completion must not re-add them (that would
        # double-count every segment).
        recalc_driver_safety_score(did)
        touch(driver)

    # Customer cascade
    if customer:
        customer["total_completed_trips"] = customer.get("total_completed_trips", 0) + 1
        customer["lifetime_revenue_cents"] = customer.get("lifetime_revenue_cents", 0) + o["final_invoice_cents"]
        recalc_customer_safety_audit_score(customer["id"])
        touch(customer)


@bp.route("/api/v1/orders/<oid>/complete-trip", methods=["POST"])
def complete_trip(oid):
    require_roles("DispatchManager")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if o["status"] not in ("IN_PROGRESS", "DISPUTED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, f"order is in state {o['status']}, cannot complete trip")
    quote = db.quotes.get(o["quote_id"])
    if quote is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "quote not found")
    _complete_trip(o, quote)
    return success_object(order_view(o))


@bp.route("/api/v1/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = require_roles("Customer", "DispatchManager")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if role == "Customer" and o.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only cancel own orders")

    quote = db.quotes.get(o["quote_id"])
    now = db.now_utc()

    if role == "Customer":
        if o["status"] == "PENDING_DEPOSIT":
            o["cancelled_by"] = "CUSTOMER"
            o["cancellation_fee_cents"] = 0
            o["refund_cents"] = 0
        elif o["status"] == "CONFIRMED":
            o["cancelled_by"] = "CUSTOMER"
            fee, refund = calc_cancellation_fee(o.get("deposit_paid_cents", 0), db.parse_iso(quote["trip_date"]), now)
            o["cancellation_fee_cents"] = fee
            o["refund_cents"] = refund
        elif o["status"] == "ASSIGNED":
            o["cancelled_by"] = "CUSTOMER"
            fee, refund = calc_cancellation_fee(o.get("deposit_paid_cents", 0), db.parse_iso(quote["trip_date"]), now)
            o["cancellation_fee_cents"] = fee
            o["refund_cents"] = refund
            _release_assignment(o)
        else:
            raise errors.make_error(errors.ERR_INVALID_STATE, f"order is in state {o['status']}, cannot cancel")
    else:  # DispatchManager
        payload = request.get_json(silent=True) or {}
        reason = payload.get("reason")
        if o["status"] == "ASSIGNED":
            if not reason or not isinstance(reason, str):
                raise errors.make_error(errors.ERR_INVALID_REQUEST, "reason is required")
            o["cancelled_by"] = "OPERATOR"
            o["cancellation_reason"] = reason
            o["cancellation_fee_cents"] = 0
            o["refund_cents"] = o.get("deposit_paid_cents", 0)
            _release_assignment(o)
        elif o["status"] == "DISPUTED":
            o["cancelled_by"] = "OPERATOR"
            if reason:
                o["cancellation_reason"] = reason
            o["cancellation_fee_cents"] = 0
            o["refund_cents"] = o.get("deposit_paid_cents", 0)
            _release_assignment(o)
        else:
            raise errors.make_error(errors.ERR_INVALID_STATE, f"order is in state {o['status']}, cannot cancel")

    o["status"] = "CANCELLED"
    touch(o)
    return success_object(order_view(o))


def _release_assignment(o):
    """Release vehicle and drivers back to AVAILABLE."""
    if o.get("assigned_vehicle_id"):
        v = db.vehicles.get(o["assigned_vehicle_id"])
        if v:
            v["status"] = "AVAILABLE"
            touch(v)
    if o.get("assigned_driver_id"):
        d = db.drivers.get(o["assigned_driver_id"])
        if d:
            d["status"] = "AVAILABLE"
            touch(d)
    if o.get("relief_driver_id"):
        d = db.drivers.get(o["relief_driver_id"])
        if d:
            d["status"] = "AVAILABLE"
            touch(d)


@bp.route("/api/v1/orders/<oid>/dispute", methods=["POST"])
def dispute_order(oid):
    user_id, role = require_roles("Customer")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if o.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only dispute own orders")
    if o["status"] != "IN_PROGRESS":
        raise errors.make_error(errors.ERR_INVALID_STATE, f"order is in state {o['status']}, cannot dispute")
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason")
    if not reason or not isinstance(reason, str):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "reason is required")
    o["cancellation_reason"] = reason
    o["status"] = "DISPUTED"
    touch(o)
    return success_object(order_view(o))


@bp.route("/api/v1/orders/<oid>/itinerary-change", methods=["POST"])
def itinerary_change(oid):
    user_id, role = require_roles("Customer", "DispatchManager")
    o = db.orders.get(oid)
    if o is None:
        raise errors.make_error(errors.ERR_NOT_FOUND, "order not found")
    if role == "Customer" and o.get("customer_id") != user_id:
        raise errors.make_error(errors.ERR_UNAUTHORIZED, "Customer may only modify own orders")
    if o["status"] not in ("PENDING_DEPOSIT", "CONFIRMED", "ASSIGNED", "IN_PROGRESS"):
        raise errors.make_error(errors.ERR_INVALID_STATE, f"order is in state {o['status']}, cannot change itinerary")

    payload = request.get_json(silent=True) or {}
    description = payload.get("description")
    if not description or not isinstance(description, str):
        raise errors.make_error(errors.ERR_INVALID_REQUEST, "description is required")
    new_estimated_hours = payload.get("new_estimated_hours")
    new_estimated_miles = payload.get("new_estimated_miles")

    change = {
        "timestamp": db.iso_now(),
        "description": description,
    }
    if new_estimated_hours is not None:
        if isinstance(new_estimated_hours, bool) or not isinstance(new_estimated_hours, (int, float)):
            raise errors.make_error(errors.ERR_INVALID_REQUEST, "new_estimated_hours must be a number")
        change["new_estimated_hours"] = float(new_estimated_hours)
    if new_estimated_miles is not None:
        if isinstance(new_estimated_miles, bool) or not isinstance(new_estimated_miles, int):
            raise errors.make_error(errors.ERR_INVALID_REQUEST, "new_estimated_miles must be an integer")
        change["new_estimated_miles"] = new_estimated_miles

    o.setdefault("itinerary_changes", []).append(change)

    # Propagate revised estimates to quote
    quote = db.quotes.get(o["quote_id"])
    if quote:
        if new_estimated_hours is not None:
            quote["estimated_hours"] = float(new_estimated_hours)
        if new_estimated_miles is not None:
            quote["estimated_miles"] = new_estimated_miles
        touch(quote)

    touch(o)
    return success_object(order_view(o))
