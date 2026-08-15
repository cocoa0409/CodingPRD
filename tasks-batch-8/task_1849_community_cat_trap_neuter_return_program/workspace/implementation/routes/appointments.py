"""Trapping appointments (PRD §3.3).

Booking check order (PRD §3.3, pinned): existence (cat, slot, voucher — body
FKs in declared order), then state (slot OPEN, day SCHEDULED), then the OCC
check of §2.9 (expected_clinic_day_version, non-optional), then voucher
ownership, then the temporal rule (trap_date strictly before the clinic day),
then the §2.7 capacity guard, and finally voucher usability (ISSUED and the
hosting clinic accepts vouchers).
"""

from flask import Blueprint

from db import db
from errors import (ApiError, ERR_CLINIC_DAY_FULL, ERR_OWNERSHIP_MISMATCH,
                    ERR_STALE_VERSION, ERR_TEMPORAL_CONFLICT,
                    ERR_VOUCHER_NOT_USABLE, invalid_state, not_found,
                    validation)
from middleware import json_body, require_roles
from response import paginate, success_object
from services.capacity_service import capacity_admits
from services.colony_service import recompute_colony
from util import (parse_datetime, public, req_str, sorted_created,
                  stamp_common, touch)

bp = Blueprint("appointments", __name__)


def get_appointment_or_404(appointment_id):
    appointment = db.appointments.get(appointment_id)
    if appointment is None:
        raise not_found("appointment")
    return appointment


def _owning_colony(appointment):
    cat = db.cats.get(appointment["cat_id"])
    if cat is None:
        return None
    return db.colonies.get(cat["colony_id"])


@bp.post("/tnr/appointments")
@require_roles("Caretaker")
def create_appointment(user_id, role):
    body = json_body()
    cat_id = req_str(body, "cat_id")
    clinic_slot_id = req_str(body, "clinic_slot_id")
    raw_trap_date = body.get("trap_date")
    if raw_trap_date is None:
        raise validation("Missing required field: 'trap_date'.")
    voucher_id = body.get("voucher_id")  # optional; null means full price

    # --- existence (priority 3), body FKs in declared order ---
    cat = db.cats.get(cat_id)
    if cat is None:
        raise not_found("cat")
    slot = db.clinic_slots.get(clinic_slot_id)
    if slot is None:
        raise not_found("clinic slot")
    voucher = None
    if voucher_id is not None:
        voucher = db.vouchers.get(voucher_id)
        if voucher is None:
            raise not_found("voucher")

    day = db.clinic_days.get(slot["clinic_day_id"])
    clinic = db.partner_clinics.get(day["clinic_id"]) if day else None

    # --- state (priority 4) ---
    if slot["status"] != "OPEN":
        raise invalid_state(
            f"Clinic slot is {slot['status']}; only OPEN slots can be booked.")
    if day["status"] != "SCHEDULED":
        raise invalid_state(
            f"Clinic day is {day['status']}; bookings require a SCHEDULED day.")

    # --- optimistic concurrency (priority 5, PRD §2.9): non-optional ---
    expected = body.get("expected_clinic_day_version")
    if expected is None or expected != day["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_clinic_day_version does not match the clinic "
                       "day's current version.")

    # --- ownership (priority 8): a committed voucher must belong to the
    # acting caretaker ---
    if voucher is not None and voucher["caretaker_id"] != user_id:
        raise ApiError(ERR_OWNERSHIP_MISMATCH, 403,
                       "The voucher belongs to a different caretaker.")

    # --- temporal (priority 10): trap_date strictly before the clinic day's
    # service_date (compared against the day's calendar date) ---
    trap_date = parse_datetime(raw_trap_date, "trap_date")
    service_midnight = day["_service_date"].replace(hour=0, minute=0, second=0,
                                                    microsecond=0)
    if not trap_date < service_midnight:
        raise ApiError(ERR_TEMPORAL_CONFLICT, 422,
                       "trap_date must fall strictly before the slot's clinic "
                       "day service_date.")

    # --- capacity guard (priority 11, PRD §2.7) ---
    if not capacity_admits(day, cat):
        raise ApiError(ERR_CLINIC_DAY_FULL, 409,
                       "Clinic day is at effective capacity for this booking's "
                       "class (adult vs kitten-in-season).")

    # --- voucher usability (priority 13) ---
    if voucher is not None:
        if voucher["status"] != "ISSUED":
            raise ApiError(ERR_VOUCHER_NOT_USABLE, 402,
                           f"Voucher is {voucher['status']}; only ISSUED "
                           "vouchers can be committed.")
        if clinic is not None and not clinic["accepts_vouchers"]:
            raise ApiError(ERR_VOUCHER_NOT_USABLE, 402,
                           "The hosting clinic does not accept vouchers.")

    # --- execute ---
    appointment = stamp_common({
        "cat_id": cat_id,
        "clinic_slot_id": clinic_slot_id,
        "trap_date": raw_trap_date,
        "voucher_id": voucher_id,
        "status": "SCHEDULED",
    })
    db.appointments[appointment["id"]] = appointment

    slot["status"] = "BOOKED"
    touch(slot)
    day["booked_count"] += 1
    touch(day)  # booking advances the day version (PRD §2.9)
    if voucher is not None:
        voucher["status"] = "COMMITTED"
        touch(voucher)

    return success_object(public(appointment), status=201)


@bp.get("/tnr/appointments/<aid>")
@require_roles("ProgramCoordinator", "Caretaker", "ClinicStaff")
def get_appointment(aid, user_id, role):
    return success_object(public(get_appointment_or_404(aid)))


@bp.post("/tnr/appointments/<aid>/mark-trapped")
@require_roles("Caretaker")
def mark_trapped(aid, user_id, role):
    appointment = get_appointment_or_404(aid)
    cat = db.cats.get(appointment["cat_id"])

    # state (priority 4) precedes the ownership rule (priority 8)
    if appointment["status"] != "SCHEDULED":
        raise invalid_state(
            f"Appointment is {appointment['status']}; only SCHEDULED "
            "appointments can be marked trapped.")
    if cat is None or cat["status"] != "AT_LARGE":
        raise invalid_state("The cat must stand AT_LARGE to be marked trapped.")

    colony = _owning_colony(appointment)
    if colony is None or colony["caretaker_id"] != user_id:
        raise ApiError(ERR_OWNERSHIP_MISMATCH, 403,
                       "Only the registered caretaker of the cat's colony may "
                       "confirm the trapping.")

    appointment["status"] = "TRAPPED"
    touch(appointment)
    cat["status"] = "TRAPPED"
    touch(cat)
    # Recompute (numerically unchanged, but refreshes the colony per PRD §2.6).
    recompute_colony(colony)
    return success_object(public(appointment))


@bp.post("/tnr/appointments/<aid>/check-in")
@require_roles("ClinicStaff")
def check_in(aid, user_id, role):
    appointment = get_appointment_or_404(aid)
    if appointment["status"] != "TRAPPED":
        raise invalid_state(
            f"Appointment is {appointment['status']}; check-in requires TRAPPED.")
    slot = db.clinic_slots.get(appointment["clinic_slot_id"])
    if slot is None or slot["status"] != "BOOKED":
        raise invalid_state("The appointment's slot must stand BOOKED.")
    day = db.clinic_days.get(slot["clinic_day_id"])
    if day is None or day["status"] != "SCHEDULED":
        raise invalid_state("The clinic day must still stand SCHEDULED.")
    cat = db.cats.get(appointment["cat_id"])
    if cat is None or cat["status"] != "TRAPPED":
        raise invalid_state("The cat must stand TRAPPED for check-in.")

    # Check-in moves only the cat; the appointment remains TRAPPED until
    # surgery completes it.
    cat["status"] = "AT_CLINIC"
    touch(cat)
    return success_object(public(appointment))


@bp.post("/tnr/appointments/<aid>/cancel")
@require_roles("Caretaker")
def cancel_appointment(aid, user_id, role):
    appointment = get_appointment_or_404(aid)
    if appointment["status"] != "SCHEDULED":
        raise invalid_state(
            f"Appointment is {appointment['status']}; only SCHEDULED "
            "appointments can be cancelled.")
    colony = _owning_colony(appointment)
    if colony is None or colony["caretaker_id"] != user_id:
        raise ApiError(ERR_OWNERSHIP_MISMATCH, 403,
                       "Only the registered caretaker of the cat's colony may "
                       "cancel the appointment.")

    appointment["status"] = "CANCELLED"
    touch(appointment)
    slot = db.clinic_slots.get(appointment["clinic_slot_id"])
    if slot is not None and slot["status"] == "BOOKED":
        slot["status"] = "RELEASED"
        touch(slot)
        day = db.clinic_days.get(slot["clinic_day_id"])
        if day is not None:
            day["booked_count"] -= 1
            touch(day)
    if appointment["voucher_id"] is not None:
        voucher = db.vouchers.get(appointment["voucher_id"])
        if voucher is not None and voucher["status"] == "COMMITTED":
            voucher["status"] = "ISSUED"
            touch(voucher)
    return success_object(public(appointment))


# --- reverse reachability -----------------------------------------------------

@bp.get("/tnr/clinic-slots/<sid>/appointments")
@require_roles("ProgramCoordinator", "ClinicStaff")
def list_slot_appointments(sid, user_id, role):
    if sid not in db.clinic_slots:
        raise not_found("clinic slot")
    rows = [a for a in db.appointments.values() if a["clinic_slot_id"] == sid]
    return paginate([public(a) for a in sorted_created(rows)])


@bp.get("/tnr/vouchers/<vid>/appointments")
@require_roles("ProgramCoordinator", "Caretaker")
def list_voucher_appointments(vid, user_id, role):
    if vid not in db.vouchers:
        raise not_found("voucher")
    rows = [a for a in db.appointments.values() if a["voucher_id"] == vid]
    return paginate([public(a) for a in sorted_created(rows)])
