"""Appointment routes — cyclic lifecycle (PRD §3.12)."""
from flask import Blueprint, request

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import (get_auth, require_role, ROLE_ADMIN, ROLE_OWNER,
                        ROLE_RECEPTIONIST)
from common import (get_body, make_record, paginate, public, touch,
                    as_str, as_int)
from services.lookups import find_or_404, require_account_owner
from services.timeutil import parse_dt
from services.appointments import has_conflict

bp = Blueprint("appointments", __name__)


def _inc_slot(slot):
    slot["booked_count"] += 1
    slot["available_count"] = max(0, slot["capacity"] - slot["booked_count"])
    touch(slot)


def _dec_slot(slot):
    slot["booked_count"] = max(0, slot["booked_count"] - 1)
    slot["available_count"] = max(0, slot["capacity"] - slot["booked_count"])
    touch(slot)


# --- Book (PRD §3.12) -------------------------------------------------------
@bp.route("/va/appointments", methods=["POST"])
def book_appointment():
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER, ROLE_RECEPTIONIST})
    body = get_body()

    # Existence validated left-to-right: account_id then slot_id (PRD §2.8).
    account_id = as_str(body, "account_id", required=True)
    account = find_or_404(db.accounts, account_id)
    slot_id = as_str(body, "slot_id", required=True)
    slot = find_or_404(db.calendar_slots, slot_id)
    origin_call_id = as_str(body, "origin_call_id", default="")
    if origin_call_id:
        find_or_404(db.calls, origin_call_id)

    # Ownership (priority 4).
    require_account_owner(account["id"], user_id, role)

    start_at = as_str(body, "start_at", required=True)
    end_at = as_str(body, "end_at", required=True)
    expected_slot_version = as_int(body, "expected_slot_version", required=True)
    sa = parse_dt(start_at, "start_at")
    ea = parse_dt(end_at, "end_at")
    if ea <= sa:
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_at must be after start_at")

    # OCC (priority 5).
    if expected_slot_version != slot["version"]:
        raise errors.err(errors.ERR_STALE_SLOT_VERSION, "expected_slot_version is stale")

    # Account suspended (priority 7).
    if account["status"] == "SUSPENDED":
        raise errors.err(errors.ERR_ACCOUNT_SUSPENDED, "Account is suspended")

    # Slot must be OPEN with available capacity (priority 12).
    if slot["status"] != "OPEN" or slot["available_count"] <= 0:
        raise errors.err(errors.ERR_SLOT_FULL, "Slot is closed or full")

    # Overlap with buffer (priority 10).
    if has_conflict(slot, start_at, end_at):
        raise errors.err(errors.ERR_SLOT_OVERLAP, "Appointment overlaps another in the slot")

    rec = make_record({
        "account_id": account_id,
        "slot_id": slot_id,
        "origin_call_id": origin_call_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "REQUESTED",
        "reschedule_count": 0,
    })
    db.appointments[rec["id"]] = rec
    _inc_slot(slot)
    return success_object(serializers.appointment(public(rec)), 201)


@bp.route("/va/appointments/<appointment_id>", methods=["GET"])
def get_appointment(appointment_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    rec = find_or_404(db.appointments, appointment_id)
    require_account_owner(rec["account_id"], user_id, role)
    return success_object(serializers.appointment(public(rec)), 200)


@bp.route("/va/appointments", methods=["GET"])
def list_appointments():
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    records = list(db.appointments.values())
    account_id = request.args.get("account_id")
    slot_id = request.args.get("slot_id")
    origin_call_id = request.args.get("origin_call_id")
    status = request.args.get("status")
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if slot_id is not None:
        records = [r for r in records if r["slot_id"] == slot_id]
    if origin_call_id is not None:
        records = [r for r in records if r["origin_call_id"] == origin_call_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if role == ROLE_OWNER:
        records = [r for r in records if r["account_id"] == user_id]
    page, meta = paginate(records)
    return success_array([serializers.appointment(public(r)) for r in page], meta, 200)


@bp.route("/va/appointments/<appointment_id>/confirm", methods=["POST"])
def confirm_appointment(appointment_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    rec = find_or_404(db.appointments, appointment_id)
    require_account_owner(rec["account_id"], user_id, role)

    if rec["status"] not in ("REQUESTED", "RESCHEDULE_REQUESTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment is not REQUESTED or RESCHEDULE_REQUESTED")

    account = db.accounts[rec["account_id"]]
    # Suspended account cannot confirm (priority 7).
    if account["status"] == "SUSPENDED":
        raise errors.err(errors.ERR_ACCOUNT_SUSPENDED, "Account is suspended")

    # Confirming a REQUESTED appointment additionally requires the slot OPEN
    # (PRD §3.12). Re-confirm from RESCHEDULE_REQUESTED requires only the
    # account posture (state machine §1.2).
    if rec["status"] == "REQUESTED":
        slot = db.calendar_slots[rec["slot_id"]]
        if slot["status"] != "OPEN":
            raise errors.err(errors.ERR_INVALID_STATE, "Slot is not OPEN")

    rec["status"] = "CONFIRMED"
    touch(rec)
    return success_object(serializers.appointment(public(rec)), 200)


@bp.route("/va/appointments/<appointment_id>/reschedule", methods=["POST"])
def reschedule_appointment(appointment_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    rec = find_or_404(db.appointments, appointment_id)
    require_account_owner(rec["account_id"], user_id, role)
    body = get_body()

    if rec["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment is not CONFIRMED")

    start_at = as_str(body, "start_at", required=True)
    end_at = as_str(body, "end_at", required=True)
    sa = parse_dt(start_at, "start_at")
    ea = parse_dt(end_at, "end_at")
    if ea <= sa:
        raise errors.err(errors.ERR_INVALID_REQUEST, "end_at must be after start_at")

    # Reschedule limit (priority 13).
    if rec["reschedule_count"] >= 3:
        raise errors.err(errors.ERR_RESCHEDULE_LIMIT, "Reschedule limit reached")

    # Overlap check excluding this appointment (priority 10).
    slot = db.calendar_slots[rec["slot_id"]]
    if has_conflict(slot, start_at, end_at, exclude_appointment_id=rec["id"]):
        raise errors.err(errors.ERR_SLOT_OVERLAP, "New interval overlaps another in the slot")

    rec["start_at"] = start_at
    rec["end_at"] = end_at
    rec["reschedule_count"] += 1
    rec["status"] = "RESCHEDULE_REQUESTED"
    touch(rec)
    return success_object(serializers.appointment(public(rec)), 200)


@bp.route("/va/appointments/<appointment_id>/complete", methods=["POST"])
def complete_appointment(appointment_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    rec = find_or_404(db.appointments, appointment_id)
    require_account_owner(rec["account_id"], user_id, role)

    if rec["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment is not CONFIRMED")
    # Logical clock must have reached end_at (PRD §3.12).
    if db.clock.epoch_seconds() < parse_dt(rec["end_at"], "end_at").timestamp():
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment end_at has not been reached")

    rec["status"] = "COMPLETED"
    touch(rec)
    return success_object(serializers.appointment(public(rec)), 200)


@bp.route("/va/appointments/<appointment_id>/no-show", methods=["POST"])
def no_show_appointment(appointment_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    rec = find_or_404(db.appointments, appointment_id)
    require_account_owner(rec["account_id"], user_id, role)

    if rec["status"] != "CONFIRMED":
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment is not CONFIRMED")
    if db.clock.epoch_seconds() < parse_dt(rec["end_at"], "end_at").timestamp():
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment end_at has not been reached")

    rec["status"] = "NO_SHOW"
    touch(rec)
    slot = db.calendar_slots[rec["slot_id"]]
    _dec_slot(slot)
    return success_object(serializers.appointment(public(rec)), 200)


@bp.route("/va/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    rec = find_or_404(db.appointments, appointment_id)
    require_account_owner(rec["account_id"], user_id, role)

    if rec["status"] not in ("REQUESTED", "CONFIRMED", "RESCHEDULE_REQUESTED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Appointment cannot be cancelled from its state")

    rec["status"] = "CANCELLED"
    touch(rec)
    slot = db.calendar_slots[rec["slot_id"]]
    _dec_slot(slot)
    return success_object(serializers.appointment(public(rec)), 200)
