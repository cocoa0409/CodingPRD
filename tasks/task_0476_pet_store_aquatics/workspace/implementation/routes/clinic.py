"""ClinicAppointment endpoints (PRD §3.7)."""
from flask import Blueprint, request

import db
from db import stamp_create, touch
from clock import clock, parse_iso
from middleware import require_auth, require_role
from response import object_response, array_response
from errors import err
from services.common import (
    get_body, lookup, parse_pagination, paginate,
    require_present, as_str, as_int, as_enum, as_datetime,
)
from services.derive import compute_loyalty_tier
from services.loyalty import whole_dollar_points, accrue
from services.serialize import appointment_out

bp = Blueprint("clinic", __name__)

READ_ROLES = ["InventoryManager", "ClinicVet", "StoreClerk", "Customer"]
SERVICE_TYPES = {"GROOMING", "VACCINE", "VET_EXAM"}
SERVICE_MULTIPLIER = {"GROOMING": 1, "VACCINE": 2, "VET_EXAM": 3}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap. Touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end


@bp.route("/clinic-appointments", methods=["POST"])
def book_appointment():
    _, role = require_auth()
    require_role(role, ["ClinicVet", "StoreClerk"])
    body = get_body()
    store_id = as_str(require_present(body, "store_id"), "store_id")
    customer_id = as_str(require_present(body, "customer_id"), "customer_id")
    lookup("stores", store_id)
    lookup("customers", customer_id)
    service_type = as_enum(require_present(body, "service_type"), "service_type", SERVICE_TYPES)
    room = as_str(require_present(body, "room"), "room")
    start_at = require_present(body, "start_at")
    end_at = require_present(body, "end_at")
    start_dt = as_datetime(start_at, "start_at")
    end_dt = as_datetime(end_at, "end_at")
    if not (end_dt > start_dt):
        raise err("ERR_INVALID_FIELD_VALUE", "end_at must be strictly after start_at.")
    fee_cents = as_int(require_present(body, "fee_cents"), "fee_cents")
    if fee_cents < 0:
        raise err("ERR_INVALID_FIELD_VALUE", "fee_cents must be >= 0.")

    # Room double-booking (PRD §3.7): same store + room, BOOKED/CHECKED_IN,
    # half-open [start, end) overlap.
    for appt in db.clinic_appointments.values():
        if (
            appt["store_id"] == store_id
            and appt["room"] == room
            and appt["status"] in ("BOOKED", "CHECKED_IN")
        ):
            if _overlaps(start_dt, end_dt, parse_iso(appt["start_at"]), parse_iso(appt["end_at"])):
                raise err("ERR_ROOM_DOUBLE_BOOKED")

    record = {
        "store_id": store_id,
        "customer_id": customer_id,
        "service_type": service_type,
        "room": room,
        "start_at": start_at,
        "end_at": end_at,
        "fee_cents": fee_cents,
        "status": "BOOKED",
    }
    stamp_create(record)
    db.clinic_appointments[record["id"]] = record
    return object_response(appointment_out(record), 201)


@bp.route("/clinic-appointments", methods=["GET"])
def list_appointments():
    _, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.clinic_appointments.values())
    for field in ("store_id", "customer_id"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, total = paginate(records, limit, offset)
    return array_response([appointment_out(r) for r in page], limit, offset, total)


@bp.route("/clinic-appointments/<appt_id>", methods=["GET"])
def get_appointment(appt_id):
    _, role = require_auth()
    require_role(role, READ_ROLES)
    record = lookup("clinic_appointments", appt_id)
    return object_response(appointment_out(record))


@bp.route("/clinic-appointments/<appt_id>/check-in", methods=["POST"])
def check_in(appt_id):
    _, role = require_auth()
    require_role(role, ["ClinicVet"])
    appt = lookup("clinic_appointments", appt_id)
    if appt["status"] != "BOOKED":
        raise err("ERR_APPOINTMENT_STATE_INVALID")
    if clock.now() < parse_iso(appt["start_at"]):
        raise err("ERR_APPOINTMENT_NOT_STARTED")
    appt["status"] = "CHECKED_IN"
    touch(appt)
    return object_response(appointment_out(appt))


@bp.route("/clinic-appointments/<appt_id>/complete", methods=["POST"])
def complete(appt_id):
    _, role = require_auth()
    require_role(role, ["ClinicVet"])
    appt = lookup("clinic_appointments", appt_id)
    if appt["status"] != "CHECKED_IN":
        raise err("ERR_APPOINTMENT_STATE_INVALID")
    appt["status"] = "COMPLETED"

    # clinic_loyalty_accrual (PRD §3.7).
    customer = db.customers.get(appt["customer_id"])
    if customer is not None:
        net = appt["fee_cents"]
        multiplier = SERVICE_MULTIPLIER[appt["service_type"]]
        earned = whole_dollar_points(net, multiplier)
        accrue(customer, net, earned)
        touch(customer)

    touch(appt)
    return object_response(appointment_out(appt))


@bp.route("/clinic-appointments/<appt_id>/cancel", methods=["POST"])
def cancel(appt_id):
    _, role = require_auth()
    require_role(role, ["ClinicVet"])
    appt = lookup("clinic_appointments", appt_id)
    if appt["status"] != "BOOKED":
        raise err("ERR_APPOINTMENT_STATE_INVALID")
    appt["status"] = "CANCELLED"
    touch(appt)
    return object_response(appointment_out(appt))


@bp.route("/clinic-appointments/<appt_id>/no-show", methods=["POST"])
def no_show(appt_id):
    _, role = require_auth()
    require_role(role, ["ClinicVet"])
    appt = lookup("clinic_appointments", appt_id)
    if appt["status"] != "BOOKED":
        raise err("ERR_APPOINTMENT_STATE_INVALID")
    if clock.now() < parse_iso(appt["end_at"]):
        raise err("ERR_APPOINTMENT_NOT_ENDED")
    appt["status"] = "NO_SHOW"
    touch(appt)
    return object_response(appointment_out(appt))
