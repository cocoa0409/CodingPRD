"""Bookings: creation, quote, confirm, payments, reschedule, cancel, weather,
and the event-day transitions (PRD §3.4, §3.6, §3.7, §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    raise_err,
    ERR_BOOKING_NOT_FOUND, ERR_VENUE_NOT_FOUND, ERR_FORBIDDEN,
    ERR_INVALID_STATE, ERR_STALE_BOOKING_VERSION,
    ERR_COMPLIANCE_SCORE_TOO_LOW, ERR_HANDWASH_STATIONS_INSUFFICIENT,
    ERR_PERMIT_NOT_ISSUED, ERR_NO_ANIMALS_CONFIRMED,
    ERR_VENUE_CAPACITY_EXCEEDED, ERR_EVENT_IN_PAST, ERR_EVENT_TOO_SOON,
    ERR_QUOTE_STALE, ERR_INSURANCE_NOT_VERIFIED, ERR_DEPOSIT_INSUFFICIENT,
    ERR_WAIVER_INCOMPLETE, ERR_STAFF_RATIO_NOT_MET, ERR_BALANCE_UNPAID,
    ERR_OVERPAYMENT, ERR_ASSESSMENT_STALE, ERR_WEATHER_HOLD_NOT_JUSTIFIED,
    ERR_INVALID_REQUEST, ERR_ANIMAL_SCHEDULE_CONFLICT, ERR_HANDLER_OVERBOOKED,
)
from middleware import require, check_customer_ownership
from response import ok
from serializers import ser_booking, ser_ledger_entry
from services import pricing
from services.cascade import (
    add_ledger_entry, animal_buffered_conflict, cancel_booking,
    handler_overbooked, recompute_handler_minutes, recompute_total_paid,
)
from util import (
    body_json, bump, new_common, now, paginate, v_dt, v_enum, v_int, v_str,
)

bp = Blueprint("bookings", __name__)

BOOKING_TYPES = {"PRIVATE_PARTY", "SCHOOL_PROGRAM", "LIBRARY_PROGRAM"}
CANCEL_REASONS = {"CUSTOMER", "WEATHER", "COMPLIANCE"}

PAYABLE_STATES = {"QUOTED", "CONFIRMED", "WEATHER_HOLD"}


def get_booking_or_404(booking_id):
    booking = store.bookings.get(booking_id)
    if booking is None:
        raise_err(ERR_BOOKING_NOT_FOUND, "Booking not found")
    return booking


def get_booking_waiver(booking_id):
    for w in store.waivers.values():
        if w["booking_id"] == booking_id:
            return w
    return None


def derive_waiver_status(waiver):
    if waiver["signed_count"] >= waiver["required_signatures"]:
        return "COMPLETE"
    if waiver["signed_count"] > 0:
        return "PARTIAL"
    return "PENDING"


# ---------------------------------------------------------------------------
# Create / read
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings")
def create_booking():
    role, uid = require({"Customer"})
    body = body_json()
    venue_id = v_str(body, "venue_id")
    start_time = v_dt(body, "start_time")
    end_time = v_dt(body, "end_time")
    guest_count = v_int(body, "guest_count")
    child_guest_count = v_int(body, "child_guest_count")
    booking_type = v_enum(body, "booking_type", BOOKING_TYPES)
    planned_handwash_stations = v_int(body, "planned_handwash_stations")
    if end_time <= start_time:
        raise_err(ERR_INVALID_REQUEST, "end_time must be strictly after start_time")

    venue = store.venues.get(venue_id)
    if venue is None:
        raise_err(ERR_VENUE_NOT_FOUND, "Venue not found")

    # Business gates, in the order enumerated by PRD §3.4.
    if not start_time > now():
        raise_err(ERR_EVENT_IN_PAST, "Event start_time is not after now")
    if start_time < now() + timedelta(hours=48):
        raise_err(ERR_EVENT_TOO_SOON, "Event starts less than 48h from now")
    if guest_count > venue["max_guest_capacity"]:
        raise_err(ERR_VENUE_CAPACITY_EXCEEDED, "guest_count exceeds venue capacity")

    booking = new_common()
    booking.update({
        "customer_id": uid,  # booking owner from X-User-ID
        "venue_id": venue_id,
        "start_time": start_time,
        "end_time": end_time,
        "guest_count": guest_count,
        "child_guest_count": child_guest_count,
        "booking_type": booking_type,
        "planned_handwash_stations": planned_handwash_stations,
        "status": "DRAFT",
        "payment_status": "UNPAID",
        "quote_fresh": False,
        "animal_subtotal_cents": None,
        "addon_subtotal_cents": None,
        "discount_cents": None,
        "surcharge_cents": None,
        "travel_fee_cents": None,
        "guest_surcharge_cents": None,
        "quoted_total_cents": None,
        "final_total_cents": None,
        "deposit_amount_cents": None,
        "total_paid_cents": 0,
        "required_handwash_stations": None,
        "required_staff_count": None,
        "compliance_screening_score": None,
        "compliance_audited_score": None,
        "actual_handwash_stations": None,
        "actual_attendance_count": None,
    })
    store.bookings[booking["id"]] = booking

    # Creating a booking auto-creates exactly one waiver.
    waiver = new_common()
    waiver.update({
        "booking_id": booking["id"],
        "required_signatures": child_guest_count,
        "signed_count": 0,
        "status": "COMPLETE" if child_guest_count == 0 else "PENDING",
    })
    store.waivers[waiver["id"]] = waiver

    return ok(ser_booking(booking), status=201)


@bp.get("/petting-zoo/bookings")
def list_bookings():
    role, uid = require({"Customer", "Coordinator", "Operator", "ComplianceOfficer"})
    bookings = list(store.bookings.values())
    customer_id = request.args.get("customer_id")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            raise_err(ERR_FORBIDDEN, "Customer may only list its own bookings")
        bookings = [b for b in bookings if b["customer_id"] == uid]
    elif customer_id is not None:
        bookings = [b for b in bookings if b["customer_id"] == customer_id]
    venue_id = request.args.get("venue_id")
    if venue_id is not None:
        bookings = [b for b in bookings if b["venue_id"] == venue_id]
    status = request.args.get("status")
    if status is not None:
        bookings = [b for b in bookings if b["status"] == status]
    payment_status = request.args.get("payment_status")
    if payment_status is not None:
        bookings = [b for b in bookings if b["payment_status"] == payment_status]
    data, meta = paginate(bookings, ser_booking)
    return ok(data, pagination=meta)


@bp.get("/petting-zoo/bookings/<booking_id>")
def get_booking(booking_id):
    role, uid = require({"Customer", "Coordinator", "Operator", "ComplianceOfficer"})
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    return ok(ser_booking(booking))


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/quote")
def quote_booking(booking_id):
    require({"Coordinator"})
    booking = get_booking_or_404(booking_id)
    if booking["status"] not in ("DRAFT", "QUOTED"):
        raise_err(ERR_INVALID_STATE, "Booking cannot be quoted from state %s" % booking["status"])

    venue = store.venues[booking["venue_id"]]
    price = pricing.booking_price(booking, "provisional")
    bas, addons, animals, guests, stations = pricing.in_scope(booking, "provisional")

    booking["animal_subtotal_cents"] = price["animal_subtotal_cents"]
    booking["addon_subtotal_cents"] = price["addon_subtotal_cents"]
    booking["discount_cents"] = price["discount_cents"]
    booking["surcharge_cents"] = price["surcharge_cents"]
    booking["travel_fee_cents"] = price["travel_fee_cents"]
    booking["guest_surcharge_cents"] = price["guest_surcharge_cents"]
    booking["quoted_total_cents"] = price["total_cents"]
    booking["deposit_amount_cents"] = pricing.deposit_amount(price["total_cents"])
    booking["required_handwash_stations"] = pricing.handwash_requirement(venue, guests, addons)
    booking["required_staff_count"] = pricing.staff_requirement(
        bas, addons, booking["child_guest_count"])
    booking["compliance_screening_score"] = pricing.compliance_score(
        venue, animals, stations, guests, addons)
    booking["status"] = "QUOTED"
    booking["quote_fresh"] = True
    bump(booking)
    return ok(ser_booking(booking))


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/payments")
def record_payment(booking_id):
    role, uid = require({"Customer"})
    body = body_json()
    amount_cents = v_int(body, "amount_cents", minimum=1)
    v_str(body, "method")
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])

    if booking["status"] not in PAYABLE_STATES:
        raise_err(ERR_OVERPAYMENT, "Booking is not in a payable state")
    if booking["total_paid_cents"] + amount_cents > booking["quoted_total_cents"]:
        raise_err(ERR_OVERPAYMENT, "Payment would exceed the quoted total")

    entry = add_ledger_entry(booking["id"], "PAYMENT", amount_cents, "Customer payment")
    recompute_total_paid(booking)
    if booking["total_paid_cents"] >= booking["quoted_total_cents"]:
        booking["payment_status"] = "PAID_IN_FULL"
    elif booking["payment_status"] == "UNPAID":
        booking["payment_status"] = "DEPOSIT_PAID"
    return ok(ser_ledger_entry(entry), status=201)


# ---------------------------------------------------------------------------
# Confirm (the nine-gate compliance check, evaluated in PRD §3.6 order)
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    role, uid = require({"Customer"})
    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])
    if booking["status"] != "QUOTED":
        raise_err(ERR_INVALID_STATE, "Booking cannot be confirmed from state %s" % booking["status"])

    venue = store.venues[booking["venue_id"]]

    # 1. compliance screening gate
    if booking["compliance_screening_score"] < pricing.CONFIRM_GATE:
        raise_err(ERR_COMPLIANCE_SCORE_TOO_LOW, "Compliance screening score below 60")
    # 2. planned handwash stations
    if booking["planned_handwash_stations"] < booking["required_handwash_stations"]:
        raise_err(ERR_HANDWASH_STATIONS_INSUFFICIENT, "Planned handwash stations below requirement")
    # 3. required permits ISSUED
    required_permits = []
    if venue["requires_animal_permit"]:
        required_permits.append("ANIMAL_EXHIBITION")
    if booking["booking_type"] in ("SCHOOL_PROGRAM", "LIBRARY_PROGRAM"):
        required_permits.append("HEALTH_DEPT")
    for ptype in required_permits:
        issued = any(
            p["booking_id"] == booking["id"] and p["permit_type"] == ptype and p["status"] == "ISSUED"
            for p in store.permits.values()
        )
        if not issued:
            raise_err(ERR_PERMIT_NOT_ISSUED, "Required permit %s is not ISSUED" % ptype)
    # 4. at least one CONFIRMED roster animal
    if not any(
        ba["booking_id"] == booking["id"] and ba["status"] == "CONFIRMED"
        for ba in store.booking_animals.values()
    ):
        raise_err(ERR_NO_ANIMALS_CONFIRMED, "No CONFIRMED animal on the booking")
    # 5. venue capacity
    if booking["guest_count"] > venue["max_guest_capacity"]:
        raise_err(ERR_VENUE_CAPACITY_EXCEEDED, "guest_count exceeds venue capacity")
    # 6. still at least 48h out
    if booking["start_time"] < now() + timedelta(hours=48):
        raise_err(ERR_EVENT_TOO_SOON, "Event starts less than 48h from now")
    # 7. quote freshness
    if not booking["quote_fresh"]:
        raise_err(ERR_QUOTE_STALE, "Quote is stale; re-quote before confirming")
    # 8. verified insurance with sufficient coverage valid past event end
    required_coverage = 500000 if booking["booking_type"] == "PRIVATE_PARTY" else 1000000
    has_insurance = any(
        c["customer_id"] == booking["customer_id"]
        and c["status"] == "VERIFIED"
        and c["coverage_amount_cents"] >= required_coverage
        and c["expires_at"] > booking["end_time"]
        for c in store.insurance_certificates.values()
    )
    if not has_insurance:
        raise_err(ERR_INSURANCE_NOT_VERIFIED, "No VERIFIED insurance certificate meets requirements")
    # 9. deposit paid
    if booking["total_paid_cents"] < booking["deposit_amount_cents"]:
        raise_err(ERR_DEPOSIT_INSUFFICIENT, "Paid total below the deposit amount")

    booking["status"] = "CONFIRMED"
    bump(booking)
    return ok(ser_booking(booking))


# ---------------------------------------------------------------------------
# Reschedule (OCC endpoint)
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/reschedule")
def reschedule_booking(booking_id):
    role, uid = require({"Customer", "Coordinator"})
    body = body_json()
    new_start = v_dt(body, "new_start_time")
    new_end = v_dt(body, "new_end_time")
    expected_version = v_int(body, "expected_booking_version")
    if new_end <= new_start:
        raise_err(ERR_INVALID_REQUEST, "new_end_time must be strictly after new_start_time")

    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])

    # A Customer reschedules a CONFIRMED booking; a Coordinator reschedules one
    # sitting in WEATHER_HOLD.
    valid = (role == "Customer" and booking["status"] == "CONFIRMED") or (
        role == "Coordinator" and booking["status"] == "WEATHER_HOLD")
    if not valid:
        raise_err(ERR_INVALID_STATE, "Booking cannot be rescheduled from state %s" % booking["status"])

    if expected_version != booking["version"]:
        raise_err(ERR_STALE_BOOKING_VERSION, "expected_booking_version does not match")

    if not new_start > now():
        raise_err(ERR_EVENT_IN_PAST, "New start_time is not after now")
    if new_start < now() + timedelta(hours=48):
        raise_err(ERR_EVENT_TOO_SOON, "New start_time is less than 48h from now")

    # Re-run roster and staffing checks against the new window.
    old_start, old_end = booking["start_time"], booking["end_time"]
    booking["start_time"], booking["end_time"] = new_start, new_end
    try:
        for ba in store.booking_animals.values():
            if ba["booking_id"] == booking["id"] and ba["status"] == "CONFIRMED":
                animal = store.animals[ba["animal_id"]]
                if animal_buffered_conflict(animal, booking, exclude_booking_id=booking["id"]):
                    raise_err(ERR_ANIMAL_SCHEDULE_CONFLICT,
                              "Animal buffered rest-window conflict on the new window")
        for sa in store.staff_assignments.values():
            if sa["booking_id"] == booking["id"] and sa["status"] == "ASSIGNED":
                if handler_overbooked(sa["handler_id"], booking, exclude_booking_id=booking["id"]):
                    raise_err(ERR_HANDLER_OVERBOOKED,
                              "Handler overbooked on the new window")
    except Exception:
        booking["start_time"], booking["end_time"] = old_start, old_end
        raise

    booking["quote_fresh"] = False
    bump(booking)
    # Handler daily totals depend on event duration; recompute affected handlers.
    for sa in store.staff_assignments.values():
        if sa["booking_id"] == booking["id"] and sa["status"] == "ASSIGNED":
            recompute_handler_minutes(sa["handler_id"])
    return ok(ser_booking(booking))


# ---------------------------------------------------------------------------
# Cancel (role-bound reasons; refund waterfall + shared cascade)
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/cancel")
def cancel_booking_endpoint(booking_id):
    role, uid = require({"Customer", "Coordinator"})
    body = body_json()
    reason = v_enum(body, "reason", CANCEL_REASONS)
    # Cancellation reasons are role-bound (authorization layer, PRD §2.1).
    if role == "Customer" and reason != "CUSTOMER":
        raise_err(ERR_FORBIDDEN, "Customer may cancel only with reason CUSTOMER")
    if role == "Coordinator" and reason not in ("WEATHER", "COMPLIANCE"):
        raise_err(ERR_FORBIDDEN, "Coordinator may cancel only with reason WEATHER or COMPLIANCE")

    booking = get_booking_or_404(booking_id)
    check_customer_ownership(role, uid, booking["customer_id"])

    if reason == "CUSTOMER":
        allowed_from = {"DRAFT", "QUOTED", "CONFIRMED", "WEATHER_HOLD"}
        target = "CANCELLED_CUSTOMER"
    elif reason == "WEATHER":
        allowed_from = {"CONFIRMED", "WEATHER_HOLD"}
        target = "CANCELLED_WEATHER"
    else:  # COMPLIANCE
        allowed_from = {"CONFIRMED"}
        target = "CANCELLED_COMPLIANCE"
    if booking["status"] not in allowed_from:
        raise_err(ERR_INVALID_STATE, "Booking cannot be cancelled from state %s" % booking["status"])

    cancel_booking(booking, reason, target)
    return ok(ser_booking(booking))


# ---------------------------------------------------------------------------
# Weather hold / release
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/weather-hold")
def weather_hold(booking_id):
    require({"Coordinator"})
    body = body_json()
    assessment_id = v_str(body, "weather_assessment_id")
    booking = get_booking_or_404(booking_id)
    if booking["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Booking is not CONFIRMED")
    assessment = store.weather_assessments.get(assessment_id)
    if assessment is None or assessment["booking_id"] != booking["id"]:
        raise_err(ERR_INVALID_REQUEST, "weather_assessment_id does not reference an assessment of this booking")
    if assessment["assessed_at"] < now() - timedelta(hours=24):
        raise_err(ERR_ASSESSMENT_STALE, "Weather assessment is older than 24h")
    if assessment["verdict"] != "MANDATORY_HOLD":
        raise_err(ERR_WEATHER_HOLD_NOT_JUSTIFIED, "Assessment verdict is not MANDATORY_HOLD")
    booking["status"] = "WEATHER_HOLD"
    bump(booking)
    return ok(ser_booking(booking))


@bp.post("/petting-zoo/bookings/<booking_id>/release-weather-hold")
def release_weather_hold(booking_id):
    require({"Coordinator"})
    booking = get_booking_or_404(booking_id)
    if booking["status"] != "WEATHER_HOLD":
        raise_err(ERR_INVALID_STATE, "Booking is not on WEATHER_HOLD")
    booking["status"] = "CONFIRMED"
    bump(booking)
    return ok(ser_booking(booking))


# ---------------------------------------------------------------------------
# Event day: dispatch -> arrive -> start-event -> complete -> finalize-invoice
# ---------------------------------------------------------------------------

@bp.post("/petting-zoo/bookings/<booking_id>/dispatch")
def dispatch_booking(booking_id):
    require({"Coordinator"})
    booking = get_booking_or_404(booking_id)
    if booking["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Booking is not CONFIRMED")
    waiver = get_booking_waiver(booking["id"])
    if waiver is None or waiver["status"] != "COMPLETE":
        raise_err(ERR_WAIVER_INCOMPLETE, "Waiver is not COMPLETE")
    assigned = sum(
        1 for sa in store.staff_assignments.values()
        if sa["booking_id"] == booking["id"] and sa["status"] == "ASSIGNED"
    )
    if assigned < booking["required_staff_count"]:
        raise_err(ERR_STAFF_RATIO_NOT_MET, "Assigned staff below required_staff_count")
    if booking["total_paid_cents"] < booking["quoted_total_cents"]:
        raise_err(ERR_BALANCE_UNPAID, "Paid total below the quoted total")
    booking["status"] = "EN_ROUTE"
    bump(booking)
    return ok(ser_booking(booking))


@bp.post("/petting-zoo/bookings/<booking_id>/arrive")
def arrive_booking(booking_id):
    require({"Coordinator"})
    booking = get_booking_or_404(booking_id)
    if booking["status"] != "EN_ROUTE":
        raise_err(ERR_INVALID_STATE, "Booking is not EN_ROUTE")
    booking["status"] = "ON_SITE_SETUP"
    bump(booking)
    return ok(ser_booking(booking))


@bp.post("/petting-zoo/bookings/<booking_id>/start-event")
def start_event(booking_id):
    require({"Coordinator"})
    body = body_json()
    actual_handwash_stations = v_int(body, "actual_handwash_stations", minimum=0)
    booking = get_booking_or_404(booking_id)
    if booking["status"] != "ON_SITE_SETUP":
        raise_err(ERR_INVALID_STATE, "Booking is not ON_SITE_SETUP")
    if actual_handwash_stations < booking["required_handwash_stations"]:
        raise_err(ERR_HANDWASH_STATIONS_INSUFFICIENT, "Actual handwash stations below requirement")
    booking["actual_handwash_stations"] = actual_handwash_stations
    booking["status"] = "IN_PROGRESS"
    bump(booking)
    return ok(ser_booking(booking))


@bp.post("/petting-zoo/bookings/<booking_id>/complete")
def complete_booking(booking_id):
    require({"Coordinator"})
    body = body_json()
    actual_attendance_count = v_int(body, "actual_attendance_count", minimum=0)
    booking = get_booking_or_404(booking_id)
    if booking["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, "Booking is not IN_PROGRESS")

    booking["actual_attendance_count"] = actual_attendance_count
    # Audited compliance variant: actual world inputs.
    venue = store.venues[booking["venue_id"]]
    bas, addons, animals, guests, stations = pricing.in_scope(booking, "final")
    booking["compliance_audited_score"] = pricing.compliance_score(
        venue, animals, stations, guests, addons)
    # Sweep still-ASSIGNED assignments to COMPLETED; recompute handler totals.
    for sa in store.staff_assignments.values():
        if sa["booking_id"] == booking["id"] and sa["status"] == "ASSIGNED":
            sa["status"] = "COMPLETED"
            bump(sa)
            recompute_handler_minutes(sa["handler_id"])
    booking["status"] = "COMPLETED"
    bump(booking)
    return ok(ser_booking(booking))


@bp.post("/petting-zoo/bookings/<booking_id>/finalize-invoice")
def finalize_invoice(booking_id):
    require({"Coordinator"})
    booking = get_booking_or_404(booking_id)
    if booking["status"] != "COMPLETED":
        raise_err(ERR_INVALID_STATE, "Booking is not COMPLETED")

    price = pricing.booking_price(booking, "final")
    booking["final_total_cents"] = price["total_cents"]
    add_ledger_entry(booking["id"], "CHARGE", price["total_cents"], "Final invoice charge")
    paid = booking["total_paid_cents"]
    if paid > price["total_cents"]:
        add_ledger_entry(booking["id"], "REFUND", paid - price["total_cents"],
                         "Overpayment refund at final invoice")
        booking["payment_status"] = "REFUND_PARTIAL"
    elif paid == price["total_cents"]:
        booking["payment_status"] = "PAID_IN_FULL"
    booking["status"] = "INVOICED"
    bump(booking)
    return ok(ser_booking(booking))
