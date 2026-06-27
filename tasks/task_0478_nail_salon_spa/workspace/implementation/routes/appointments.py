"""Appointments: booking, add-on attach, and the two parallel state machines
(PRD §3.5-§3.14)."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, get_enum, get_int,
                    parse_pagination, paginate)
from db import db
from clock import clock
from datetime_util import parse_iso8601, format_iso8601
from errors import (err, ERR_INVALID_STATE, ERR_ITEM_RETIRED, ERR_FORBIDDEN,
                    ERR_STATION_NOT_STERILE, ERR_LICENSE_EXPIRED,
                    ERR_TECHNICIAN_DOUBLE_BOOKED, ERR_STATION_TURNOVER_CONFLICT,
                    ERR_NO_SHOW_TOO_EARLY, ERR_DEPOSIT_REQUIRED,
                    ERR_INSUFFICIENT_LOYALTY, ERR_GIFT_CARD_OVERDRAW,
                    ERR_STALE_VERSION, ERR_INVALID_REQUEST)
from middleware import authorize
from lookup import (get_appointment, get_client, get_technician, get_station,
                    get_menu_item, get_add_on, get_gift_card)
from derive import (client_effective_strikes, station_sanitation_status,
                    station_in_service_appointment_id,
                    NO_SHOW_GRACE_MINUTES)
from response import success_object, success_list
from serialize import appointment_out, appointment_add_on_out
import services as svc

from datetime import timedelta

bp = Blueprint("appointments", __name__)


# ---- booking (PRD §3.5) ----------------------------------------------------

@bp.route("/appointments", methods=["POST"])
def create_appointment():
    authorize({"FrontDesk", "SalonManager"})
    body = json_body(optional=False)
    client_id = get_str(body, "client_id", required=True)
    technician_id = get_str(body, "technician_id", required=True)
    station_id = get_str(body, "station_id", required=True)
    service_item_id = get_str(body, "service_item_id", required=True)
    origin = get_enum(body, "origin", ["WALK_IN", "APPOINTMENT"], required=True)
    start_at_raw = body.get("start_at")

    # FK existence in body order (PRD §2.6): client, technician, station, service
    client = get_client(client_id)
    get_technician(technician_id)
    get_station(station_id)
    service = get_menu_item(service_item_id)

    # start_at: WALK_IN defaults to current logical clock if omitted (PRD §3.5)
    if start_at_raw is None or start_at_raw == "":
        if origin == "WALK_IN":
            start_at = format_iso8601(clock.now())
        else:
            raise err(ERR_INVALID_REQUEST, "start_at required for APPOINTMENT")
    else:
        start_at = format_iso8601(parse_iso8601(start_at_raw))

    # ServiceMenuItem must be active to book (PRD §3.5)
    if not service["is_active"]:
        raise err(ERR_ITEM_RETIRED, "Cannot book a retired service")

    rec = make_record({
        "client_id": client_id,
        "technician_id": technician_id,
        "station_id": station_id,
        "service_item_id": service_item_id,
        "origin": origin,
        "start_at": start_at,
        "end_at": None,
        "booking_status": "REQUESTED",
        "payment_status": "UNPAID",
        "deposit_due_cents": 0,
        "deposit_paid_cents": 0,
        "subtotal_cents": 0,
        "loyalty_points_redeemed": 0,
        "gift_card_id": None,
        "total_charged_cents": 0,
        "technician_earning_cents": 0,
        "no_show_strike_charged": False,
    })
    db.appointments[rec["id"]] = rec

    # end_at from service duration (no add-ons yet at booking)
    rec["end_at"] = svc.compute_end_at(rec)

    # deposit assessment (PRD §3.5): deposit_due_cents per client strike posture.
    rec["deposit_due_cents"] = svc.assess_deposit(client)
    # deposit_required derives from the client's strikes on read; no stored flag.

    return success_object(appointment_out(rec), status=201)


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    authorize({"FrontDesk", "SalonManager"})
    items = list(db.appointments.values())
    for key in ("client_id", "technician_id", "station_id", "service_item_id",
                "gift_card_id", "booking_status", "payment_status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([appointment_out(a) for a in page], limit, offset, total)


@bp.route("/appointments/<aid>", methods=["GET"])
def get_one_appointment(aid):
    user_id, role = authorize({"FrontDesk", "SalonManager", "Client", "Technician"})
    rec = get_appointment(aid)
    if role == "Client" and user_id != rec["client_id"]:
        raise err(ERR_FORBIDDEN, "Client may only read their own appointment")
    if role == "Technician" and user_id != rec["technician_id"]:
        raise err(ERR_FORBIDDEN, "Technician may only read their own appointment")
    return success_object(appointment_out(rec), status=200)


# ---- add-on attach (PRD §3.5) ---------------------------------------------

@bp.route("/appointments/<aid>/add-ons", methods=["POST"])
def attach_add_on(aid):
    authorize({"FrontDesk", "SalonManager"})
    rec = get_appointment(aid)
    body = json_body(optional=False)
    add_on_id = get_str(body, "add_on_id", required=True)
    expected_version = get_int(body, "expected_appointment_version", required=True)

    add_on = get_add_on(add_on_id)

    # state: only a REQUESTED appointment accepts attaches (transition defined
    # from REQUESTED) (PRD §3.5)
    if rec["booking_status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Add-ons may only be attached to a REQUESTED appointment")

    # item retirement (priority 7)
    if not add_on["is_active"]:
        raise err(ERR_ITEM_RETIRED, "Cannot attach a retired add-on")

    # OCC: expected_appointment_version must equal stored version (PRD §3.5
    # supplies the version they last observed; mismatch -> stale)
    if expected_version != rec["version"]:
        raise err(ERR_STALE_VERSION, "Stale appointment version")

    junction = make_record({
        "appointment_id": aid,
        "add_on_id": add_on_id,
        "price_cents_snapshot": add_on["price_cents"],
        "extra_minutes_snapshot": add_on["extra_minutes"],
    }, with_common=False)  # junction row: id + created_at only (PRD §2.4)
    db.appointment_add_ons[junction["id"]] = junction

    # recompute end_at; increment appointment version (PRD §3.5)
    rec["end_at"] = svc.compute_end_at(rec)
    touch(rec)

    return success_object(appointment_add_on_out(junction), status=201)


@bp.route("/appointments/<aid>/add-ons", methods=["GET"])
def list_appointment_add_ons(aid):
    user_id, role = authorize({"FrontDesk", "SalonManager", "Client", "Technician"})
    rec = get_appointment(aid)
    if role == "Client" and user_id != rec["client_id"]:
        raise err(ERR_FORBIDDEN, "Client may only read their own appointment")
    if role == "Technician" and user_id != rec["technician_id"]:
        raise err(ERR_FORBIDDEN, "Technician may only read their own appointment")
    items = [r for r in db.appointment_add_ons.values() if r["appointment_id"] == aid]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([appointment_add_on_out(r) for r in page], limit, offset, total)


# ---- pay deposit (PRD §3.6) -----------------------------------------------

@bp.route("/appointments/<aid>/pay-deposit", methods=["POST"])
def pay_deposit(aid):
    authorize({"FrontDesk", "SalonManager"})
    rec = get_appointment(aid)
    # transition defined: payment_status UNPAID, booking REQUESTED/CONFIRMED,
    # deposit owed (PRD §3.6).
    if rec["payment_status"] != "UNPAID":
        raise err(ERR_INVALID_STATE, "Payment is not UNPAID")
    if rec["booking_status"] not in ("REQUESTED", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "Deposit may only be paid while REQUESTED or CONFIRMED")
    if rec["deposit_due_cents"] <= 0:
        raise err(ERR_INVALID_STATE, "No deposit is owed")
    rec["deposit_paid_cents"] = rec["deposit_due_cents"]
    rec["payment_status"] = "DEPOSIT_HELD"
    touch(rec)
    return success_object(appointment_out(rec), status=200)


# ---- confirm (PRD §3.7) ----------------------------------------------------

@bp.route("/appointments/<aid>/confirm", methods=["POST"])
def confirm_appointment(aid):
    authorize({"FrontDesk", "SalonManager"})
    rec = get_appointment(aid)
    # state: only from REQUESTED (PRD §3.7); undefined transition -> ERR_INVALID_STATE
    if rec["booking_status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Only a REQUESTED appointment can be confirmed")

    # fiscal: deposit-required client must have deposit held (priority 14)
    client = db.clients[rec["client_id"]]
    _, deposit_required = client_effective_strikes(client)
    if deposit_required and rec["payment_status"] != "DEPOSIT_HELD":
        raise err(ERR_DEPOSIT_REQUIRED, "A deposit must be held before confirming")

    # snapshot subtotal + recompute end_at BEFORE the scheduling guards so the
    # guarded window reflects the confirmed window (PRD §3.7).
    rec["subtotal_cents"] = svc.compute_subtotal(rec)
    rec["end_at"] = svc.compute_end_at(rec)

    # temporal: technician double-book (priority 11)
    if svc.technician_double_booked(rec):
        raise err(ERR_TECHNICIAN_DOUBLE_BOOKED, "Technician window overlaps another appointment")
    # temporal: station turnover buffer (priority 12)
    if svc.station_turnover_conflict(rec):
        raise err(ERR_STATION_TURNOVER_CONFLICT, "Station turnover buffer violated")

    rec["booking_status"] = "CONFIRMED"
    touch(rec)
    return success_object(appointment_out(rec), status=200)


# ---- check-in (PRD §3.8) ---------------------------------------------------

@bp.route("/appointments/<aid>/check-in", methods=["POST"])
def check_in(aid):
    authorize({"FrontDesk", "SalonManager"})
    rec = get_appointment(aid)
    if rec["booking_status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Only a CONFIRMED appointment can be checked in")

    service = db.menu_items[rec["service_item_id"]]
    station = db.stations[rec["station_id"]]
    technician = db.technicians[rec["technician_id"]]

    # sterilization gate (priority 8): if service.requires_sterile_station OR
    # station.requires_autoclave, station.sanitation_status must be CLEAN.
    if service["requires_sterile_station"] or station["requires_autoclave"]:
        if station_sanitation_status(station) != "CLEAN":
            raise err(ERR_STATION_NOT_STERILE, "Station is not sterile")

    # license/status gate (priority 9): technician ACTIVE and license non-expired.
    if technician["status"] != "ACTIVE" or parse_iso8601(technician["license_expiry"]) <= clock.now():
        raise err(ERR_LICENSE_EXPIRED, "Technician is not fit to work")

    rec["booking_status"] = "CHECKED_IN"
    touch(rec)
    return success_object(appointment_out(rec), status=200)


# ---- start-service (PRD §3.9) ---------------------------------------------

@bp.route("/appointments/<aid>/start-service", methods=["POST"])
def start_service(aid):
    user_id, role = authorize({"Technician", "SalonManager"})
    rec = get_appointment(aid)
    # ownership: Technician acts on own appointment (PRD §3.9 / §2.1)
    if role == "Technician" and user_id != rec["technician_id"]:
        raise err(ERR_FORBIDDEN, "Technician may only start their own appointment")
    if rec["booking_status"] != "CHECKED_IN":
        raise err(ERR_INVALID_STATE, "Only a CHECKED_IN appointment can start service")
    # station must be free (in_service_appointment_id null) (PRD §3.9)
    if station_in_service_appointment_id(rec["station_id"]) is not None:
        raise err(ERR_INVALID_STATE, "Station is already occupied")
    rec["booking_status"] = "IN_SERVICE"
    # in_service_appointment_id is derived from booking_status==IN_SERVICE; the
    # station's updated_at/version refresh per PRD §2.10 cross-entity effect.
    touch(db.stations[rec["station_id"]])
    touch(rec)
    return success_object(appointment_out(rec), status=200)


# ---- checkout (PRD §3.10) --------------------------------------------------

@bp.route("/appointments/<aid>/checkout", methods=["POST"])
def checkout(aid):
    authorize({"FrontDesk", "SalonManager"})
    rec = get_appointment(aid)
    body = json_body(optional=False)
    expected_version = get_int(body, "expected_appointment_version", required=True)
    loyalty_points_redeemed = get_int(body, "loyalty_points_redeemed", required=False, default=0, minimum=0)
    gift_card_id = body.get("gift_card_id")

    gift_card = None
    if gift_card_id is not None:
        gift_card = get_gift_card(gift_card_id)  # FK existence (PRD §2.6)

    # state: must be IN_SERVICE (priority 6)
    if rec["booking_status"] != "IN_SERVICE":
        raise err(ERR_INVALID_STATE, "Only an IN_SERVICE appointment can be checked out")
    # payment not already settled (PRD §3.10 precondition)
    if rec["payment_status"] not in ("UNPAID", "DEPOSIT_HELD"):
        raise err(ERR_INVALID_STATE, "Appointment payment already settled")

    # business: gift card ACTIVE (priority 16, also a §3.10 precondition)
    if gift_card is not None and gift_card["status"] != "ACTIVE":
        raise err(ERR_GIFT_CARD_OVERDRAW, "Gift card is not ACTIVE")

    # business fiscal: loyalty sufficiency (priority 15)
    client = db.clients[rec["client_id"]]
    if loyalty_points_redeemed > client["loyalty_points_balance"]:
        raise err(ERR_INSUFFICIENT_LOYALTY, "Insufficient loyalty points")

    # OCC: expected_appointment_version must match (priority 17)
    if expected_version != rec["version"]:
        raise err(ERR_STALE_VERSION, "Stale appointment version")

    svc.run_checkout_settlement(rec, gift_card, loyalty_points_redeemed)
    return success_object(appointment_out(rec), status=200)


# ---- cancel (PRD §3.12) ----------------------------------------------------

@bp.route("/appointments/<aid>/cancel", methods=["POST"])
def cancel_appointment(aid):
    user_id, role = authorize({"FrontDesk", "SalonManager", "Client"})
    rec = get_appointment(aid)
    if role == "Client" and user_id != rec["client_id"]:
        raise err(ERR_FORBIDDEN, "Client may only cancel their own appointment")
    if rec["booking_status"] not in ("REQUESTED", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "Only a REQUESTED or CONFIRMED appointment can be cancelled")
    svc.run_cancel(rec)
    return success_object(appointment_out(rec), status=200)


# ---- mark-no-show (PRD §3.13) ---------------------------------------------

@bp.route("/appointments/<aid>/mark-no-show", methods=["POST"])
def mark_no_show(aid):
    authorize({"FrontDesk", "SalonManager"})
    rec = get_appointment(aid)
    # state: only from CONFIRMED, and idempotency guard (PRD §3.13)
    if rec["booking_status"] != "CONFIRMED" or rec["no_show_strike_charged"]:
        raise err(ERR_INVALID_STATE, "Only a CONFIRMED, un-charged appointment can be marked no-show")
    # grace: clock >= start_at + 15min (priority 13)
    grace_boundary = parse_iso8601(rec["start_at"]) + timedelta(minutes=NO_SHOW_GRACE_MINUTES)
    if clock.now() < grace_boundary:
        raise err(ERR_NO_SHOW_TOO_EARLY, "No-show grace period has not elapsed")
    svc.run_mark_no_show(rec)
    return success_object(appointment_out(rec), status=200)


# ---- refund-settled (PRD §3.14) -------------------------------------------

@bp.route("/appointments/<aid>/refund-settled", methods=["POST"])
def refund_settled(aid):
    authorize({"SalonManager"})
    rec = get_appointment(aid)
    if rec["payment_status"] != "SETTLED":
        raise err(ERR_INVALID_STATE, "Only a SETTLED appointment can be refunded")
    svc.run_refund_settled(rec)
    return success_object(appointment_out(rec), status=200)
