"""Bookings: 45-minute HELD holds on PUBLISHED excursions behind the
conservative capacity gate; CONFIRM quotes fares, redeems rain-checks and runs
the dining table selector; CANCEL applies the 48-hour refund rule; CHECK_IN
requires the excursion to be BOARDING."""
from datetime import timedelta

from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_roles
from db import clock_date, clock_now, new_entity, public, touch
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_CLASS_FULL,
    ERR_DINING_SERVICE_FULL,
    ERR_EXCURSION_NOT_BOOKABLE,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PARTY_TOO_LARGE_FOR_DINING,
    ERR_RAIN_CHECK_INVALID,
    ERR_VALIDATION,
)
from services.core import (
    HOLD_MINUTES,
    conservative_fits,
    compute_refund,
    quote_fare,
    recompute_manifest,
    select_dining_table,
)
from timeutil import iso_z
from validators import body, opt_str, paginate, pagination, req_enum, req_int, req_str

bp = Blueprint("bookings", __name__)

BOOKING_CLASSES = ("COACH", "FIRST_CLASS", "DINING")
DINING_SERVICES = ("EARLY", "LATE")


def get_booking_or_404(booking_id):
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise ApiError(ERR_NOT_FOUND, "Booking not found", 404)
    return booking


@bp.post("/railroad/bookings")
def create_booking():
    require_roles("StationAgent")
    data = body()
    excursion_id = req_str(data, "excursion_id")
    # Tier 5 gate: only PUBLISHED excursions are bookable.
    exc = db.excursions.get(excursion_id)
    if exc is not None and exc["status"] != "PUBLISHED":
        raise ApiError(
            ERR_EXCURSION_NOT_BOOKABLE,
            "Bookings can only be created on a PUBLISHED excursion",
            409,
        )
    customer_email = req_str(data, "customer_email")
    class_code = req_enum(data, "class_code", BOOKING_CLASSES)
    party_size = req_int(data, "party_size")
    # Tier 7: body FK existence.
    if exc is None:
        raise ApiError(ERR_INVALID_REFERENCE, "excursion_id does not exist", 422)
    # Tier 8f: a dining table seats four.
    if class_code == "DINING" and party_size > 4:
        raise ApiError(
            ERR_PARTY_TOO_LARGE_FOR_DINING,
            "DINING party_size is limited to 4",
            422,
        )
    # Tier 8g: party bounds and the dining_service conditional field.
    if not (1 <= party_size <= 8):
        raise ApiError(
            ERR_VALIDATION, "party_size must be between 1 and 8", 400
        )
    dining_service = data.get("dining_service")
    if class_code == "DINING":
        if not isinstance(dining_service, str) or dining_service not in DINING_SERVICES:
            raise ApiError(
                ERR_VALIDATION,
                "dining_service (EARLY|LATE) is required for DINING bookings",
                400,
            )
    else:
        if dining_service is not None:
            raise ApiError(
                ERR_VALIDATION,
                "dining_service is only allowed for DINING bookings",
                400,
            )
        dining_service = None
    # Tier 10a: conservative capacity gate (counts unexpired HELD too).
    if not conservative_fits(exc["id"], class_code, party_size):
        raise ApiError(
            ERR_CLASS_FULL,
            "Conservative class capacity is insufficient for this party",
            409,
        )
    booking = new_entity(
        {
            "excursion_id": exc["id"],
            "customer_email": customer_email,
            "class_code": class_code,
            "party_size": party_size,
            "dining_service": dining_service,
            "status": "HELD",
            "expires_at": iso_z(clock_now() + timedelta(minutes=HOLD_MINUTES)),
            "unit_fare_cents": None,
            "total_price_cents": None,
            "paid_cents": None,
            "refund_cents": 0,
            "dining_table_number": None,
            "dining_car_assignment_id": None,
        }
    )
    db.bookings[booking["id"]] = booking
    # HOLIDAY excursions pre-count unexpired HELD diners in the DRAFT manifest.
    recompute_manifest(exc["id"])
    return success_obj(public(booking), 201)


@bp.get("/railroad/bookings/<bid>")
def get_booking(bid):
    require_roles(*ALL_ROLES)
    return success_obj(public(get_booking_or_404(bid)), 200)


@bp.get("/railroad/bookings")
def list_bookings():
    require_roles(*ALL_ROLES)
    items = list(db.bookings.values())
    excursion_id = request.args.get("excursion_id")
    customer_email = request.args.get("customer_email")
    status = request.args.get("status")
    dining_car = request.args.get("dining_car_assignment_id")
    if excursion_id is not None:
        items = [b for b in items if b["excursion_id"] == excursion_id]
    if customer_email is not None:
        items = [b for b in items if b["customer_email"] == customer_email]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if dining_car is not None:
        items = [b for b in items if b["dining_car_assignment_id"] == dining_car]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([public(b) for b in page], limit, offset, total)


@bp.post("/railroad/bookings/<bid>/events")
def booking_event(bid):
    require_roles("StationAgent")
    booking = get_booking_or_404(bid)
    data = body()
    event_type = data.get("event_type")

    if event_type == "CONFIRM":
        if booking["status"] != "HELD":
            raise ApiError(
                ERR_INVALID_STATE, "Only a HELD booking can be confirmed", 409
            )
        exc = db.excursions.get(booking["excursion_id"])
        # Tier 7: the optional rain-check FK must resolve.
        rc_id = opt_str(data, "redeemed_rain_check_id")
        rain_check = None
        if rc_id is not None:
            rain_check = db.rain_checks.get(rc_id)
            if rain_check is None:
                raise ApiError(
                    ERR_INVALID_REFERENCE,
                    "redeemed_rain_check_id does not exist",
                    422,
                )
        # Tier 10a: re-run the conservative capacity gate (excluding self).
        if not conservative_fits(
            booking["excursion_id"],
            booking["class_code"],
            booking["party_size"],
            exclude_booking_id=booking["id"],
        ):
            raise ApiError(
                ERR_CLASS_FULL,
                "Conservative class capacity is insufficient for this party",
                409,
            )
        # Tier 10b: a free dining table in the requested service.
        chosen = None
        if booking["class_code"] == "DINING":
            chosen = select_dining_table(
                exc, booking["dining_service"], booking["party_size"]
            )
            if chosen is None:
                raise ApiError(
                    ERR_DINING_SERVICE_FULL,
                    "No free table in the requested dining service",
                    409,
                )
        # Tier 10c: rain-check validity (ISSUED, email match, not expired).
        if rain_check is not None:
            if (
                rain_check["status"] != "ISSUED"
                or rain_check["customer_email"] != booking["customer_email"]
                or clock_date() > rain_check["expires_on"]
            ):
                raise ApiError(
                    ERR_RAIN_CHECK_INVALID,
                    "Rain-check is not ISSUED, belongs to another customer, or "
                    "is expired",
                    422,
                )
        unit, total, paid = quote_fare(
            exc, booking["class_code"], booking["party_size"], rain_check
        )
        booking["unit_fare_cents"] = unit
        booking["total_price_cents"] = total
        booking["paid_cents"] = paid
        if chosen is not None:
            car, table_no = chosen
            booking["dining_car_assignment_id"] = car["id"]
            booking["dining_table_number"] = table_no
        booking["status"] = "CONFIRMED"
        touch(booking)
        if rain_check is not None:
            # Fully consumed even when its value exceeds the new total.
            rain_check["status"] = "REDEEMED"
            rain_check["redeemed_booking_id"] = booking["id"]
            touch(rain_check)
        recompute_manifest(booking["excursion_id"])
    elif event_type == "CANCEL":
        if booking["status"] == "HELD":
            booking["status"] = "CANCELLED"  # never paid -> no refund
            touch(booking)
            recompute_manifest(booking["excursion_id"])
        elif booking["status"] == "CONFIRMED":
            exc = db.excursions.get(booking["excursion_id"])
            booking["refund_cents"] = compute_refund(exc, booking)
            if booking["class_code"] == "DINING":
                # Free the table for the selector to hand out again.
                booking["dining_table_number"] = None
                booking["dining_car_assignment_id"] = None
            booking["status"] = "CANCELLED"
            touch(booking)
            recompute_manifest(booking["excursion_id"])
        else:
            raise ApiError(
                ERR_INVALID_STATE,
                "Only HELD or CONFIRMED bookings can be cancelled",
                409,
            )
    elif event_type == "CHECK_IN":
        if booking["status"] != "CONFIRMED":
            raise ApiError(
                ERR_INVALID_STATE, "Only a CONFIRMED booking can check in", 409
            )
        exc = db.excursions.get(booking["excursion_id"])
        if exc is None or exc["status"] != "BOARDING":
            raise ApiError(
                ERR_INVALID_STATE,
                "Check-in requires the excursion to be BOARDING",
                409,
            )
        booking["status"] = "CHECKED_IN"
        touch(booking)
    else:
        raise ApiError(ERR_VALIDATION, "Unknown event_type: %r" % event_type, 400)
    return success_obj(public(booking), 200)
