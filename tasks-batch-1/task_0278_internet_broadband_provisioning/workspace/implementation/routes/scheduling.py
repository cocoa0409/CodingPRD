"""InstallSlot and InstallAppointment endpoints (PRD §3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import touch
from errors import err
from middleware import get_user_context, require_role
from response import object_response, array_response
from services.helpers import (get_json_body, lookup, require_fields,
                              require_positive_int, require_int, require_iso,
                              paginate, sorted_by_created, check_owner)
from services.serialize import public, public_list
from timeutil import parse_iso

bp = Blueprint("scheduling", __name__)


# --- InstallSlot ---

@bp.route("/install-slots", methods=["POST"])
def create_install_slot():
    _uid, role = get_user_context()
    require_role(role, {"Dispatcher"})
    body = get_json_body()
    require_fields(body, ["technician_id", "window_start_iso", "window_end_iso",
                          "capacity"])
    tech = lookup(db.technicians, body["technician_id"])
    start = require_iso(body, "window_start_iso")
    end = require_iso(body, "window_end_iso")
    capacity = require_positive_int(body, "capacity")
    if not (end > start):
        err("ERR_INVALID_REQUEST", "window_end_iso must be after window_start_iso.")
    rec = db.make_record({
        "technician_id": tech["id"],
        "window_start_iso": body["window_start_iso"],
        "window_end_iso": body["window_end_iso"],
        "capacity": capacity,
        "booked_count": 0,
        "status": "OPEN",
    }, versioned=db.VERSIONED)
    db.install_slots[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.route("/install-slots/<rid>", methods=["GET"])
def get_install_slot(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    rec = lookup(db.install_slots, rid)
    return object_response(public(rec), 200)


@bp.route("/install-slots", methods=["GET"])
def list_install_slots():
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    recs = list(db.install_slots.values())
    for f in ("technician_id", "status"):
        val = request.args.get(f)
        if val is not None:
            recs = [r for r in recs if r.get(f) == val]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)


# --- InstallAppointment ---

@bp.route("/install-appointments", methods=["POST"])
def book_appointment():
    uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent"})
    body = get_json_body()
    require_fields(body, ["service_order_id", "install_slot_id", "start_iso",
                          "end_iso", "expected_account_version"])
    # Existence (priority 3): body FKs.
    order = lookup(db.service_orders, body["service_order_id"])
    slot = lookup(db.install_slots, body["install_slot_id"])
    # Body well-formedness (priority 4).
    start = require_iso(body, "start_iso")
    end = require_iso(body, "end_iso")
    expected_version = require_int(body, "expected_account_version")
    if not (end > start):
        err("ERR_INVALID_REQUEST", "end_iso must be after start_iso.")

    account = db.accounts.get(order["account_id"])

    # State (priority 5): the order must be DRAFT and TECH_INSTALL to book.
    if order["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Order must be DRAFT to book an appointment.")
    if order["install_mode"] != "TECH_INSTALL":
        err("ERR_INVALID_STATE", "Booking requires a TECH_INSTALL order.")

    # Ownership (priority 6).
    if account is not None:
        check_owner(role, uid, account)

    # Serviceability (priority 7) then speed (priority 8) on the account address.
    address = db.service_addresses.get(account["service_address_id"]) if account else None
    plan = db.service_plans.get(order["requested_plan_id"])
    if address is None or address["coverage_status"] != "SERVICEABLE":
        err("ERR_ADDRESS_NOT_SERVICEABLE", "Address is not SERVICEABLE.")
    if plan is not None and plan["download_mbps"] > address["max_serviceable_mbps"]:
        err("ERR_PLAN_EXCEEDS_SERVICEABLE_SPEED",
            "Requested plan exceeds the address serviceable speed.")

    # Slot capacity (priority 10).
    if slot["booked_count"] >= slot["capacity"]:
        err("ERR_SLOT_AT_CAPACITY", "Install slot is at capacity.")

    # Technician double-booking (priority 11): [start, end + travel_buffer)
    # must not intersect any other BOOKED/COMPLETED appointment of the same tech.
    tech = db.technicians.get(slot["technician_id"])
    buffer_min = tech["travel_buffer_minutes"] if tech else 0
    new_start = start
    new_end = end + timedelta(minutes=buffer_min)
    for a in db.install_appointments.values():
        if a["technician_id"] != slot["technician_id"]:
            continue
        if a["status"] not in ("BOOKED", "COMPLETED"):
            continue
        a_start = parse_iso(a["start_iso"])
        a_end = parse_iso(a["end_iso"]) + timedelta(
            minutes=(db.technicians.get(a["technician_id"], {}) or {}).get(
                "travel_buffer_minutes", 0))
        # Half-open intersection test.
        if new_start < a_end and a_start < new_end:
            err("ERR_TECHNICIAN_DOUBLE_BOOKED",
                "Technician is already booked in this interval.")

    # Appointment within slot window (priority 12).
    win_start = parse_iso(slot["window_start_iso"])
    win_end = parse_iso(slot["window_end_iso"])
    if not (win_start <= start and end <= win_end):
        err("ERR_APPOINTMENT_OUTSIDE_SLOT",
            "Appointment must fall entirely within the slot window.")

    # OCC (priority 16).
    if account is not None and expected_version != account["version"]:
        err("ERR_STALE_ACCOUNT_VERSION",
            "expected_account_version does not match the account version.")

    # Create appointment.
    rec = db.make_record({
        "service_order_id": order["id"],
        "install_slot_id": slot["id"],
        "technician_id": slot["technician_id"],
        "start_iso": body["start_iso"],
        "end_iso": body["end_iso"],
        "status": "BOOKED",
    }, versioned=db.VERSIONED)
    db.install_appointments[rec["id"]] = rec

    # Side effects: slot booked_count += 1 (-> FULL at capacity).
    slot["booked_count"] += 1
    if slot["booked_count"] >= slot["capacity"]:
        slot["status"] = "FULL"
    touch(slot)

    # Order DRAFT -> SCHEDULED.
    order["status"] = "SCHEDULED"
    touch(order)

    # Account version bump (OCC-guarded write).
    if account is not None:
        touch(account)

    return object_response(public(rec), 201)


@bp.route("/install-appointments/<rid>", methods=["GET"])
def get_appointment(rid):
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    rec = lookup(db.install_appointments, rid)
    return object_response(public(rec), 200)


@bp.route("/install-appointments", methods=["GET"])
def list_appointments():
    _uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent", "NetworkOps", "Dispatcher"})
    recs = list(db.install_appointments.values())
    for f in ("service_order_id", "install_slot_id", "technician_id"):
        val = request.args.get(f)
        if val is not None:
            recs = [r for r in recs if r.get(f) == val]
    recs = sorted_by_created(recs)
    window, limit, offset, total, has_more = paginate(recs)
    return array_response(public_list(window), limit, offset, total, has_more, 200)


@bp.route("/install-appointments/<rid>/complete", methods=["POST"])
def complete_appointment(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.install_appointments, rid)
    if rec["status"] != "BOOKED":
        err("ERR_INVALID_STATE", "Appointment must be BOOKED to complete.")
    rec["status"] = "COMPLETED"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/install-appointments/<rid>/no-show", methods=["POST"])
def no_show(rid):
    _uid, role = get_user_context()
    require_role(role, {"ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.install_appointments, rid)
    if rec["status"] != "BOOKED":
        err("ERR_INVALID_STATE", "Appointment must be BOOKED to mark no-show.")
    rec["status"] = "NO_SHOW"
    touch(rec)
    _release_slot(rec["install_slot_id"])
    return object_response(public(rec), 200)


@bp.route("/install-appointments/<rid>/cancel", methods=["POST"])
def cancel_appointment(rid):
    uid, role = get_user_context()
    require_role(role, {"Customer", "ProvisioningAgent"})
    get_json_body()
    rec = lookup(db.install_appointments, rid)
    # Ownership for Customer: via the order's account.
    if role == "Customer":
        order = db.service_orders.get(rec["service_order_id"])
        account = db.accounts.get(order["account_id"]) if order else None
        if account is not None:
            check_owner(role, uid, account)
    if rec["status"] != "BOOKED":
        err("ERR_INVALID_STATE", "Appointment must be BOOKED to cancel.")
    rec["status"] = "CANCELLED"
    touch(rec)
    _release_slot(rec["install_slot_id"])
    return object_response(public(rec), 200)


def _release_slot(slot_id):
    slot = db.install_slots.get(slot_id)
    if slot is None:
        return
    slot["booked_count"] = max(0, slot["booked_count"] - 1)
    if slot["booked_count"] < slot["capacity"]:
        slot["status"] = "OPEN"
    touch(slot)
