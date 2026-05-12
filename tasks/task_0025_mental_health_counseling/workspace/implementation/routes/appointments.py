"""Appointment endpoints."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from clock import now, iso, parse_iso
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services.validation import (
    get_body, require_str, optional_str, APPOINTMENT_TYPES, PAYMENT_MODES,
)
from services.calculations import (
    settlement_charge_breakdown, appointment_refund, forward_refund_estimate,
    DEFAULT_LIST_PRICE,
)
from services.cascades import cancel_confirmed_appointment
from services.scheduling import check_invariants


bp = Blueprint("appointments", __name__)


def _public(a: dict) -> dict:
    return db.public(a)


def _ownership_ok(appt: dict) -> bool:
    if g.user_role == "PlatformAdmin":
        return True
    if g.user_role == "Client" and g.user_id == appt["client_id"]:
        return True
    if g.user_role == "Counselor" and g.user_id == appt["counselor_id"]:
        return True
    return False


@bp.route("/counseling/appointments", methods=["POST"])
@require_auth(roles={"Client"})
def create_appointment():
    body = get_body()
    counselor_id = require_str(body, "counselor_id")
    client_id = require_str(body, "client_id")
    slot_id = require_str(body, "slot_id")
    appointment_type = require_str(body, "appointment_type")
    payment_mode = require_str(body, "payment_mode")

    if g.user_id != client_id:
        raise err("ERR_FORBIDDEN", "Client may only book for self")

    if appointment_type not in APPOINTMENT_TYPES:
        raise err("ERR_VALIDATION", f"invalid appointment_type: {appointment_type}")
    if payment_mode not in PAYMENT_MODES:
        raise err("ERR_VALIDATION", f"invalid payment_mode: {payment_mode}")

    counselor = db.counselors.get(counselor_id)
    if counselor is None:
        raise err("ERR_REF_NOT_FOUND", f"counselor_id {counselor_id} not found")
    client = db.clients.get(client_id)
    if client is None:
        raise err("ERR_REF_NOT_FOUND", f"client_id {client_id} not found")
    slot = db.availability_slots.get(slot_id)
    if slot is None:
        raise err("ERR_REF_NOT_FOUND", f"slot_id {slot_id} not found")

    if slot["counselor_id"] != counselor_id:
        raise err("ERR_VALIDATION", "slot does not belong to counselor")

    if counselor["status"] != "ACTIVE":
        raise err("ERR_COUNSELOR_NOT_ACTIVE",
                  f"Counselor not ACTIVE ({counselor['status']})")

    if slot["status"] != "OPEN":
        if slot["status"] in ("HELD", "BOOKED"):
            raise err("ERR_SLOT_TAKEN", "Slot is no longer available")
        raise err("ERR_INVALID_STATE", f"Slot status {slot['status']} not bookable")

    cur = now()
    start_at = parse_iso(slot["start_at"])
    if cur >= start_at - timedelta(hours=1):
        raise err("ERR_BOOKING_TOO_LATE",
                  "Booking attempted too close to start time")

    # Assessment gate
    asmt = client.get("assessment_status", "PENDING")
    if asmt == "PENDING" and appointment_type != "INTAKE":
        raise err("ERR_INTAKE_REQUIRED",
                  "Client must complete INTAKE first")
    if asmt == "IN_PROGRESS" and appointment_type == "INTAKE":
        raise err("ERR_INTAKE_ALREADY_IN_PROGRESS",
                  "Client already has INTAKE in progress")

    if slot["channel"] not in counselor["supported_channels"]:
        raise err("ERR_CHANNEL_NOT_SUPPORTED",
                  f"channel {slot['channel']} not supported")

    # Re-check scheduling invariants (excludes the slot being booked since
    # it's already in OPEN and counted; but we are checking the proposed booking
    # against the counselor's overall load — the invariants on slot creation
    # already enforced caps. Booking does not exceed those caps because the
    # slot already exists. Skip recheck — slot caps were checked at creation.)

    # Hold the slot
    appt = {
        "counselor_id": counselor_id,
        "client_id": client_id,
        "slot_id": slot_id,
        "appointment_type": appointment_type,
        "channel": slot["channel"],
        "status": "HOLD",
        "payment_mode": payment_mode,
        "list_price_cents": DEFAULT_LIST_PRICE,
        "refund_state": "NONE",
        "cancellation_reason": None,
        "confirmed_at": None,
        "started_at": None,
        "ended_at": None,
        "start_at": slot["start_at"],
        "end_at": slot["end_at"],
    }
    db.stamp_create(appt, common_fields=True)
    db.appointments[appt["id"]] = appt

    slot["status"] = "HELD"
    slot["held_until"] = iso(cur + timedelta(minutes=15))
    slot["held_appointment_id"] = appt["id"]
    db.stamp_update(slot)

    return success(_public(appt), 201)


@bp.route("/counseling/appointments/<id>/confirm", methods=["POST"])
@require_auth(roles={"Client"})
def confirm_appointment(id):
    appt = db.appointments.get(id)
    if appt is None:
        raise err("ERR_NOT_FOUND", f"Appointment {id} not found")
    if g.user_id != appt["client_id"]:
        raise err("ERR_FORBIDDEN", "Client may only confirm own appointment")

    if appt["status"] != "HOLD":
        raise err("ERR_INVALID_STATE",
                  f"Appointment status {appt['status']} cannot be confirmed")

    counselor = db.counselors[appt["counselor_id"]]
    client = db.clients[appt["client_id"]]
    slot = db.availability_slots[appt["slot_id"]]

    if counselor["status"] != "ACTIVE":
        raise err("ERR_COUNSELOR_NOT_ACTIVE",
                  f"Counselor not ACTIVE ({counselor['status']})")

    cur = now()
    held_until = parse_iso(slot["held_until"]) if slot.get("held_until") else None
    if held_until is None or cur >= held_until:
        raise err("ERR_HOLD_EXPIRED", "Slot hold has expired")

    if appt["payment_mode"] == "PACKAGE":
        if client.get("package_balance_sessions", 0) < 1:
            raise err("ERR_INSUFFICIENT_PACKAGE_BALANCE",
                      "Client has no package sessions remaining")

    # Confirm
    appt["status"] = "CONFIRMED"
    appt["confirmed_at"] = iso(cur)
    db.stamp_update(appt)

    slot["status"] = "BOOKED"
    db.stamp_update(slot)

    if appt["payment_mode"] == "PACKAGE":
        client["package_balance_sessions"] -= 1
        db.stamp_update(client)

    if appt["appointment_type"] == "INTAKE" and client.get("assessment_status") == "PENDING":
        client["assessment_status"] = "IN_PROGRESS"
        db.stamp_update(client)

    # CHARGE row
    components = settlement_charge_breakdown(
        list_price_cents=appt["list_price_cents"],
        payment_mode=appt["payment_mode"],
        revenue_share_bps=counselor["revenue_share_bps"],
    )
    row = {
        "appointment_id": appt["id"],
        "direction": "CHARGE",
        "gross_amount_cents": components["gross_amount_cents"],
        "tax_cents": components["tax_cents"],
        "counselor_share_cents": components["counselor_share_cents"],
        "platform_share_cents": components["platform_share_cents"],
        "payout_id": None,
    }
    db.stamp_create(row, common_fields=False)
    db.settlement_ledger[row["id"]] = row

    return success(_public(appt))


@bp.route("/counseling/appointments/<id>/refund-estimate", methods=["GET"])
@require_auth(roles={"Client", "Counselor", "PlatformAdmin"})
def refund_estimate(id):
    appt = db.appointments.get(id)
    if appt is None:
        raise err("ERR_NOT_FOUND", f"Appointment {id} not found")
    if not _ownership_ok(appt):
        raise err("ERR_FORBIDDEN", "Not authorized for this appointment")

    cur = now()
    start_at = parse_iso(appt["start_at"])
    hours = (start_at - cur).total_seconds() / 3600.0
    refund_state = forward_refund_estimate(hours)
    list_price = appt["list_price_cents"]
    if refund_state == "FULL_REFUNDED":
        gross = list_price
    elif refund_state == "PARTIAL_REFUNDED":
        from services.calculations import round_half_up
        from decimal import Decimal
        gross = round_half_up(Decimal(list_price) * Decimal("0.50"))
    else:
        gross = 0
    return success({
        "appointment_id": id,
        "hours_to_start": hours,
        "refund_state": refund_state,
        "estimated_gross_amount_cents": gross,
    })


@bp.route("/counseling/appointments/<id>/cancel", methods=["POST"])
@require_auth(roles={"Client", "Counselor", "PlatformAdmin"})
def cancel_appointment(id):
    appt = db.appointments.get(id)
    if appt is None:
        raise err("ERR_NOT_FOUND", f"Appointment {id} not found")
    if not _ownership_ok(appt):
        raise err("ERR_FORBIDDEN", "Not authorized for this appointment")

    body = get_body()
    reason_in = optional_str(body, "reason")

    status = appt["status"]
    if status == "HOLD":
        # Manual cancel of a HOLD: slot -> RELEASED, no refund
        appt["status"] = "CANCELLED"
        appt["cancellation_reason"] = "CLIENT_CANCEL"
        db.stamp_update(appt)
        slot = db.availability_slots.get(appt.get("slot_id"))
        if slot is not None and slot["status"] == "HELD":
            slot["status"] = "RELEASED"
            slot["held_until"] = None
            slot["held_appointment_id"] = None
            db.stamp_update(slot)
        return success(_public(appt))

    if status != "CONFIRMED":
        raise err("ERR_INVALID_STATE",
                  f"Appointment status {status} cannot be cancelled")

    # Determine cancellation_reason from actor
    if g.user_role == "Client":
        reason = "CLIENT_CANCEL"
    elif g.user_role == "Counselor":
        reason = "COUNSELOR_CANCEL"
    else:
        # PlatformAdmin: default to client cancel unless body says otherwise
        # The PRD doesn't constrain admin's reason; admin cancellation typically
        # mirrors a counselor-driven full refund per §3.2 disqualification cascade.
        # Use COUNSELOR_CANCEL semantics for admin (full refund).
        reason = "COUNSELOR_CANCEL"

    cancel_confirmed_appointment(
        appt=appt, reason=reason,
        actor_role=g.user_role, actor_user_id=g.user_id,
    )
    return success(_public(appt))


@bp.route("/counseling/appointments/<id>/reschedule", methods=["POST"])
@require_auth(roles={"Client", "Counselor"})
def reschedule_appointment(id):
    appt = db.appointments.get(id)
    if appt is None:
        raise err("ERR_NOT_FOUND", f"Appointment {id} not found")
    if not _ownership_ok(appt):
        raise err("ERR_FORBIDDEN", "Not authorized for this appointment")

    body = get_body()
    new_slot_id = require_str(body, "new_slot_id")

    if appt["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE",
                  f"Appointment status {appt['status']} cannot be rescheduled")

    new_slot = db.availability_slots.get(new_slot_id)
    if new_slot is None:
        raise err("ERR_REF_NOT_FOUND", f"new_slot_id {new_slot_id} not found")

    counselor = db.counselors[appt["counselor_id"]]
    cur = now()
    start_at = parse_iso(appt["start_at"])
    if cur >= start_at - timedelta(hours=24):
        raise err("ERR_RESCHEDULE_WINDOW_CLOSED",
                  "Reschedule window has closed")

    if new_slot["counselor_id"] != appt["counselor_id"]:
        raise err("ERR_VALIDATION", "new_slot must belong to same counselor")
    if new_slot["status"] != "OPEN":
        if new_slot["status"] in ("HELD", "BOOKED"):
            raise err("ERR_SLOT_TAKEN", "New slot is not available")
        raise err("ERR_INVALID_STATE",
                  f"new_slot status {new_slot['status']} not bookable")

    if new_slot["channel"] not in counselor["supported_channels"]:
        raise err("ERR_CHANNEL_NOT_SUPPORTED",
                  f"channel {new_slot['channel']} not supported")

    if counselor["status"] != "ACTIVE":
        raise err("ERR_COUNSELOR_NOT_ACTIVE",
                  f"Counselor not ACTIVE ({counselor['status']})")

    # Price drift check: compare current platform list price to frozen one.
    current_list_price = DEFAULT_LIST_PRICE
    if appt["list_price_cents"] != current_list_price:
        raise err("ERR_PRICE_DRIFT",
                  "List price drifted from frozen value; cancel and rebook")

    # Release old slot
    old_slot = db.availability_slots.get(appt["slot_id"])
    if old_slot is not None:
        old_slot["status"] = "RELEASED"
        old_slot["held_until"] = None
        old_slot["held_appointment_id"] = None
        db.stamp_update(old_slot)

    # Bind new slot directly to BOOKED
    new_slot["status"] = "BOOKED"
    new_slot["held_appointment_id"] = appt["id"]
    db.stamp_update(new_slot)

    appt["slot_id"] = new_slot_id
    appt["channel"] = new_slot["channel"]
    appt["start_at"] = new_slot["start_at"]
    appt["end_at"] = new_slot["end_at"]
    db.stamp_update(appt)

    return success(_public(appt))


@bp.route("/counseling/appointments/<id>/start", methods=["POST"])
@require_auth(roles={"Counselor"})
def start_session(id):
    appt = db.appointments.get(id)
    if appt is None:
        raise err("ERR_NOT_FOUND", f"Appointment {id} not found")
    if g.user_id != appt["counselor_id"]:
        raise err("ERR_FORBIDDEN", "Counselor may only start own session")
    if appt["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE",
                  f"Appointment status {appt['status']} cannot be started")
    counselor = db.counselors[appt["counselor_id"]]
    if counselor["status"] != "ACTIVE":
        raise err("ERR_COUNSELOR_NOT_ACTIVE",
                  f"Counselor not ACTIVE ({counselor['status']})")

    cur = now()
    start_at = parse_iso(appt["start_at"])
    if cur < start_at - timedelta(minutes=5) or cur >= start_at + timedelta(minutes=15):
        raise err("ERR_INVALID_STATE",
                  "Cannot start outside [start_at - 5m, start_at + 15m) window")

    appt["status"] = "IN_SESSION"
    appt["started_at"] = iso(cur)
    db.stamp_update(appt)
    return success(_public(appt))


@bp.route("/counseling/appointments/<id>/complete", methods=["POST"])
@require_auth(roles={"Counselor"})
def complete_session(id):
    appt = db.appointments.get(id)
    if appt is None:
        raise err("ERR_NOT_FOUND", f"Appointment {id} not found")
    if g.user_id != appt["counselor_id"]:
        raise err("ERR_FORBIDDEN", "Counselor may only complete own session")
    if appt["status"] != "IN_SESSION":
        raise err("ERR_INVALID_STATE",
                  f"Appointment status {appt['status']} cannot be completed")

    # Implicit completion gate: a counseling record must exist
    has_record = any(
        r["appointment_id"] == id for r in db.counseling_records.values()
    )
    if not has_record:
        raise err("ERR_INVALID_STATE",
                  "Cannot complete without a CounselingRecord")

    cur = now()
    appt["status"] = "COMPLETED"
    appt["ended_at"] = iso(cur)
    db.stamp_update(appt)

    client = db.clients[appt["client_id"]]
    if client.get("assessment_status") == "IN_PROGRESS" and appt["appointment_type"] == "INTAKE":
        client["assessment_status"] = "COMPLETED"
        db.stamp_update(client)

    return success(_public(appt))


@bp.route("/counseling/appointments", methods=["GET"])
@require_auth(roles={"Client", "Counselor", "PlatformAdmin"})
def list_appointments():
    limit, offset = get_pagination()
    counselor_id = request.args.get("counselor_id")
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    from_s = request.args.get("from")
    to_s = request.args.get("to")

    items = list(db.appointments.values())
    if g.user_role == "Client":
        items = [a for a in items if a["client_id"] == g.user_id]
    elif g.user_role == "Counselor":
        items = [a for a in items if a["counselor_id"] == g.user_id]

    if counselor_id:
        items = [a for a in items if a["counselor_id"] == counselor_id]
    if client_id:
        items = [a for a in items if a["client_id"] == client_id]
    if status:
        items = [a for a in items if a["status"] == status]
    if from_s:
        try:
            from_dt = parse_iso(from_s)
        except ValueError:
            raise err("ERR_VALIDATION", "from must be ISO 8601")
        items = [a for a in items if a.get("start_at") and parse_iso(a["start_at"]) >= from_dt]
    if to_s:
        try:
            to_dt = parse_iso(to_s)
        except ValueError:
            raise err("ERR_VALIDATION", "to must be ISO 8601")
        items = [a for a in items if a.get("start_at") and parse_iso(a["start_at"]) < to_dt]

    items.sort(key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([_public(a) for a in page], limit, offset, total)


@bp.route("/counseling/appointments/<id>", methods=["GET"])
@require_auth(roles={"Client", "Counselor", "PlatformAdmin"})
def get_appointment(id):
    appt = db.appointments.get(id)
    if appt is None:
        raise err("ERR_NOT_FOUND", f"Appointment {id} not found")
    if not _ownership_ok(appt):
        raise err("ERR_FORBIDDEN", "Not authorized for this appointment")
    return success(_public(appt))
