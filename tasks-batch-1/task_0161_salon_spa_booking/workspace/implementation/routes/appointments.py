"""Appointment routes: book, fetch, list, confirm/cancel/no-show (PRD §3.3-§3.4).

Booking runs the fixed eight-step domain check order from PRD §3.3 after the
universal auth/authz/existence checks:
  1. ERR_RESOURCE_TYPE_MISMATCH  (service<->resource type, package match)
  2. ERR_CLIENT_NOT_BOOKABLE     (suspended/archived bookability)
  3. ERR_BOOKING_IN_PAST         (start_utc strictly after current_utc)
  4. ERR_RESOURCE_INACTIVE       (stylist ACTIVE, resource ACTIVE)
  5. ERR_STYLIST_DOUBLE_BOOKED   (buffer-padded overlap)
  6. ERR_RESOURCE_DOUBLE_BOOKED  (bare occupancy overlap)
  7. ERR_PACKAGE_EXHAUSTED       (active purchase, sessions_remaining >= 1)
  8. ERR_STALE_STYLIST_VERSION   (OCC on Stylist.version)
ERR_INVALID_REQUEST backstops field validity.
"""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import err
from lookups import get_or_404, get_salon, get_scoped
from response import success
from util import stamp_create, touch, public, parse_dt
import validate as v
from calculations import appointment_service_quote
from cascades import restore_package_session, apply_no_show_cascade
from middleware import authenticate, require_roles, require_owns_client
from routes.common import auth, json_body, list_response, ALL_ROLES

bp = Blueprint("appointments", __name__)

NON_TERMINAL = {"BOOKED", "CONFIRMED"}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) ∩ [b_start, b_end) != empty.

    Touching at a boundary (one ends exactly where the next begins) is NOT an
    overlap (PRD §3.3).
    """
    return a_start < b_end and b_start < a_end


@bp.post("/appointments")
def book():
    caller = authenticate()
    require_roles(caller, ("SalonOwner", "FrontDesk", "Client"))
    body = json_body()
    v.require_object(body)

    # --- existence + tenant scoping (priority 3) ---
    salon_id = v.req_str(body, "salon_id")
    salon = get_salon(salon_id)

    client_id = v.req_str(body, "client_id")
    # Entity-backed ownership: a Client may only self-book (PRD §2.1 / §3.3).
    require_owns_client(caller, client_id)
    stylist_id = v.req_str(body, "stylist_id")
    resource_id = v.req_str(body, "resource_id")
    service_id = v.req_str(body, "service_id")
    start_raw = v.req_str(body, "start_utc")
    # expected_stylist_version required (OCC carrier, PRD §2.7)
    if "expected_stylist_version" not in body or body["expected_stylist_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_stylist_version is required")
    expected_stylist_version = v.req_int(body, "expected_stylist_version")
    package_purchase_id = v.opt_str(body, "package_purchase_id", default=None)

    client = get_scoped(db.clients, client_id, salon["id"])
    stylist = get_scoped(db.stylists, stylist_id, salon["id"])
    resource = get_scoped(db.resources, resource_id, salon["id"])
    service = get_scoped(db.services, service_id, salon["id"])

    package_purchase = None
    package = None
    if package_purchase_id is not None:
        # Existence of the purchase (priority 3). Tenant scoping is via its client.
        package_purchase = get_or_404(db.package_purchases, package_purchase_id)
        package = db.packages.get(package_purchase["package_id"])
        if package is None:
            raise err("ERR_NOT_FOUND", "package not found")

    start_utc = parse_dt(start_raw, "start_utc")

    # --- 1. referential consistency: service<->resource type + package match ---
    if service["requires_room"] and resource["resource_type"] != "ROOM":
        raise err("ERR_RESOURCE_TYPE_MISMATCH", "service requires a ROOM resource")
    if not service["requires_room"] and resource["resource_type"] != "CHAIR":
        raise err("ERR_RESOURCE_TYPE_MISMATCH", "service requires a CHAIR resource")
    if package_purchase is not None:
        if package_purchase["client_id"] != client["id"]:
            raise err("ERR_RESOURCE_TYPE_MISMATCH", "package purchase not owned by booking client")
        if package["service_id"] != service["id"]:
            raise err("ERR_RESOURCE_TYPE_MISMATCH", "package service does not match booked service")

    # --- 2. client bookability ---
    if client["status"] == "ARCHIVED":
        raise err("ERR_CLIENT_NOT_BOOKABLE", "archived client may not be booked")
    if caller.role == "Client" and client["status"] == "SUSPENDED":
        raise err("ERR_CLIENT_NOT_BOOKABLE", "suspended client may not self-book")

    # --- 3. temporality: start strictly after current_utc ---
    current_utc = parse_dt(salon["current_utc"], "current_utc")
    if not (start_utc > current_utc):
        raise err("ERR_BOOKING_IN_PAST", "start_utc must be strictly after current time")

    # --- 4. resource liveness ---
    if stylist["status"] != "ACTIVE" or resource["status"] != "ACTIVE":
        raise err("ERR_RESOURCE_INACTIVE", "stylist or resource is not active")

    # Compute intervals.
    duration = timedelta(minutes=service["duration_minutes"])
    end_utc = start_utc + duration
    buffer = timedelta(minutes=stylist["buffer_minutes"])
    stylist_start = start_utc - buffer
    stylist_end = end_utc + buffer

    # --- 5. stylist availability (buffer-padded overlap) ---
    for appt in db.appointments.values():
        if appt["stylist_id"] != stylist["id"] or appt["status"] not in NON_TERMINAL:
            continue
        o_start = parse_dt(appt["start_utc"]) - timedelta(minutes=stylist["buffer_minutes"])
        o_end = parse_dt(appt["end_utc"]) + timedelta(minutes=stylist["buffer_minutes"])
        if _intervals_overlap(stylist_start, stylist_end, o_start, o_end):
            raise err("ERR_STYLIST_DOUBLE_BOOKED", "stylist has an overlapping appointment")

    # --- 6. resource availability (bare occupancy overlap) ---
    for appt in db.appointments.values():
        if appt["resource_id"] != resource["id"] or appt["status"] not in NON_TERMINAL:
            continue
        o_start = parse_dt(appt["start_utc"])
        o_end = parse_dt(appt["end_utc"])
        if _intervals_overlap(start_utc, end_utc, o_start, o_end):
            raise err("ERR_RESOURCE_DOUBLE_BOOKED", "resource has an overlapping appointment")

    # --- 7. package availability ---
    if package_purchase is not None:
        if package_purchase["status"] != "ACTIVE" or package_purchase["sessions_remaining"] < 1:
            raise err("ERR_PACKAGE_EXHAUSTED", "package purchase exhausted")

    # --- 8. OCC: expected_stylist_version ---
    if expected_stylist_version != stylist["version"]:
        raise err("ERR_STALE_STYLIST_VERSION", "stylist version is stale")

    # --- snapshot quote + deposit (calc appointment_service_quote) ---
    has_package = package_purchase is not None
    quote, deposit = appointment_service_quote(service, client["id"], has_package)

    appointment = {
        "salon_id": salon["id"],
        "client_id": client["id"],
        "stylist_id": stylist["id"],
        "resource_id": resource["id"],
        "service_id": service["id"],
        "package_purchase_id": package_purchase_id,
        "start_utc": start_raw,
        "end_utc": end_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{end_utc.microsecond // 1000:03d}Z",
        "status": "BOOKED",
        "quoted_service_price_cents": quote,
        "deposit_held_cents": deposit,
        # Internal flag: a package session is only *redeemed* (consumed) at
        # checkout (PRD §3.5), never at booking. Cancel / no-show / void restore
        # a session ONLY when one was actually redeemed (PRD §3.4/§3.6).
        "_session_redeemed": False,
    }
    stamp_create(appointment)
    db.appointments[appointment["id"]] = appointment

    # Side effect: advance serving stylist's version (schedule changed, PRD §3.3).
    touch(stylist)

    return success(public(appointment), status=201)


@bp.get("/appointments/<appointment_id>")
def get_appointment(appointment_id):
    auth(ALL_ROLES)
    appointment = get_or_404(db.appointments, appointment_id)
    return success(public(appointment), status=200)


@bp.get("/appointments")
def list_appointments():
    auth(ALL_ROLES)
    filters = {
        "salon_id": request.args.get("salon_id"),
        "client_id": request.args.get("client_id"),
        "stylist_id": request.args.get("stylist_id"),
        "resource_id": request.args.get("resource_id"),
        "service_id": request.args.get("service_id"),
        "package_purchase_id": request.args.get("package_purchase_id"),
        "status": request.args.get("status"),
    }

    def pred(a):
        for key, val in filters.items():
            if val is not None and a.get(key) != val:
                return False
        return True

    page, meta = list_response(db.appointments, pred)
    return success(page, status=200, response_type="array", pagination=meta)


@bp.post("/appointments/<appointment_id>/confirm")
def confirm(appointment_id):
    auth(("SalonOwner", "FrontDesk"))
    appointment = get_or_404(db.appointments, appointment_id)
    client = db.clients[appointment["client_id"]]
    # Permitted only while BOOKED and client not ARCHIVED.
    if appointment["status"] != "BOOKED" or client["status"] == "ARCHIVED":
        raise err("ERR_INVALID_STATE", "appointment cannot be confirmed")
    appointment["status"] = "CONFIRMED"
    touch(appointment)
    return success(public(appointment), status=200)


@bp.post("/appointments/<appointment_id>/cancel")
def cancel(appointment_id):
    caller = auth(("SalonOwner", "FrontDesk", "Client"))
    appointment = get_or_404(db.appointments, appointment_id)
    # Entity-backed ownership: a Client may only cancel its own appointment.
    require_owns_client(caller, appointment["client_id"])
    salon = db.salons[appointment["salon_id"]]

    # State: must be BOOKED/CONFIRMED and current_utc strictly before start.
    if appointment["status"] not in NON_TERMINAL:
        raise err("ERR_INVALID_STATE", "appointment not in a cancellable state")
    current_utc = parse_dt(salon["current_utc"])
    start_utc = parse_dt(appointment["start_utc"])
    if not (current_utc < start_utc):
        raise err("ERR_INVALID_STATE", "cannot cancel after the slot has begun")

    appointment["status"] = "CANCELLED"
    # Refund full deposit to wallet (cascade on Client).
    client = db.clients[appointment["client_id"]]
    client["wallet_credit_cents"] += appointment["deposit_held_cents"]
    touch(client)
    # Restore a package session ONLY if this appointment had actually redeemed
    # one (PRD §3.4). Redemption happens at checkout (PRD §3.5); a still-BOOKED/
    # CONFIRMED appointment never consumed a session, so nothing is restored.
    if appointment.get("_session_redeemed"):
        restore_package_session(appointment.get("package_purchase_id"))
    touch(appointment)
    return success(public(appointment), status=200)


@bp.post("/appointments/<appointment_id>/no-show")
def no_show(appointment_id):
    auth(("SalonOwner", "FrontDesk"))
    appointment = get_or_404(db.appointments, appointment_id)
    salon = db.salons[appointment["salon_id"]]

    # State: must be BOOKED/CONFIRMED and the slot must have begun.
    if appointment["status"] not in NON_TERMINAL:
        raise err("ERR_INVALID_STATE", "appointment not in a no-showable state")
    current_utc = parse_dt(salon["current_utc"])
    start_utc = parse_dt(appointment["start_utc"])
    if not (current_utc >= start_utc):
        raise err("ERR_INVALID_STATE", "cannot no-show before the slot has begun")

    appointment["status"] = "NO_SHOW"
    client = db.clients[appointment["client_id"]]
    apply_no_show_cascade(appointment, salon, client)
    # Restore a package session ONLY if this appointment had actually redeemed
    # one (PRD §3.4). A still-BOOKED/CONFIRMED appointment never consumed a
    # session at checkout, so there is nothing to restore.
    if appointment.get("_session_redeemed"):
        restore_package_session(appointment.get("package_purchase_id"))
    touch(appointment)
    return success(public(appointment), status=200)
