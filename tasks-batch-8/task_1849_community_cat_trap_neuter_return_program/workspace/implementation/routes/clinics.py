"""Partner clinics, clinic days, and clinic slots (PRD §3.2).

Clinic day creation materializes the full slot inventory: base_capacity +
surge_capacity OPEN slots with sequential slot_index starting at 1. Closing a
day runs the no-show sweep (BOOKED slots whose appointment still stands
SCHEDULED become USED, their appointments NO_SHOW, committed vouchers release
back to ISSUED, cats stay AT_LARGE) and releases remaining OPEN slots; the
sweep does NOT decrement booked_count. Cancelling a day requires
booked_count == 0 and releases its OPEN slots.
"""

from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_DAY_HAS_BOOKINGS, ERR_TEMPORAL_CONFLICT,
                    invalid_state, not_found)
from middleware import json_body, require_roles
from response import paginate, success_object
from util import (now_dt, opt_int_default, parse_datetime, public, req_int,
                  req_str, sorted_created, stamp_common, touch)

bp = Blueprint("clinics", __name__)


def get_day_or_404(day_id):
    day = db.clinic_days.get(day_id)
    if day is None:
        raise not_found("clinic day")
    return day


def get_slot_or_404(slot_id):
    slot = db.clinic_slots.get(slot_id)
    if slot is None:
        raise not_found("clinic slot")
    return slot


# --- partner clinics ----------------------------------------------------------

@bp.post("/tnr/partner-clinics")
@require_roles("ProgramCoordinator")
def create_partner_clinic(user_id, role):
    body = json_body()
    name = req_str(body, "name")
    reimbursement = req_int(body, "voucher_reimbursement_cents", minimum=1)
    accepts = body.get("accepts_vouchers", True)
    if not isinstance(accepts, bool):
        from errors import validation
        raise validation("Field 'accepts_vouchers' must be a boolean.")

    clinic = stamp_common({
        "name": name,
        "voucher_reimbursement_cents": reimbursement,
        "accepts_vouchers": accepts,
        "status": "ACTIVE",
    })
    db.partner_clinics[clinic["id"]] = clinic
    return success_object(public(clinic), status=201)


@bp.get("/tnr/partner-clinics/<cid>")
@require_roles("ProgramCoordinator", "ClinicStaff")
def get_partner_clinic(cid, user_id, role):
    clinic = db.partner_clinics.get(cid)
    if clinic is None:
        raise not_found("partner clinic")
    return success_object(public(clinic))


@bp.get("/tnr/partner-clinics/<cid>/clinic-days")
@require_roles("ProgramCoordinator", "ClinicStaff", "Caretaker")
def list_clinic_days(cid, user_id, role):
    if cid not in db.partner_clinics:
        raise not_found("partner clinic")
    rows = [d for d in db.clinic_days.values() if d["clinic_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return paginate([public(d) for d in sorted_created(rows)])


# --- clinic days & slots ------------------------------------------------------

@bp.post("/tnr/clinic-days")
@require_roles("ClinicStaff")
def create_clinic_day(user_id, role):
    body = json_body()
    clinic_id = req_str(body, "clinic_id")
    if clinic_id not in db.partner_clinics:
        raise not_found("partner clinic")
    base_capacity = req_int(body, "base_capacity", minimum=1)
    surge_capacity = opt_int_default(body, "surge_capacity", 0, minimum=0)
    raw_service_date = body.get("service_date")
    if raw_service_date is None:
        from errors import validation
        raise validation("Missing required field: 'service_date'.")
    service_date = parse_datetime(raw_service_date, "service_date")

    # service_date is compared as a calendar date; a date in the past relative
    # to the logical clock is rejected (PRD §2.4/§3.2).
    if service_date.date() < now_dt().date():
        raise ApiError(ERR_TEMPORAL_CONFLICT, 422,
                       "Clinic day service_date may not be in the past.")

    day = stamp_common({
        "clinic_id": clinic_id,
        "service_date": raw_service_date,
        "base_capacity": base_capacity,
        "surge_capacity": surge_capacity,
        "booked_count": 0,
        "status": "SCHEDULED",
    })
    day["_service_date"] = service_date
    db.clinic_days[day["id"]] = day

    for index in range(1, base_capacity + surge_capacity + 1):
        slot = stamp_common({
            "clinic_day_id": day["id"],
            "slot_index": index,
            "status": "OPEN",
        })
        db.clinic_slots[slot["id"]] = slot

    return success_object(public(day), status=201)


@bp.get("/tnr/clinic-days/<did>")
@require_roles("ProgramCoordinator", "ClinicStaff", "Caretaker")
def get_clinic_day(did, user_id, role):
    return success_object(public(get_day_or_404(did)))


@bp.get("/tnr/clinic-days/<did>/slots")
@require_roles("ProgramCoordinator", "ClinicStaff", "Caretaker")
def list_day_slots(did, user_id, role):
    get_day_or_404(did)
    rows = [s for s in db.clinic_slots.values() if s["clinic_day_id"] == did]
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    rows = sorted(rows, key=lambda s: s["slot_index"])
    return paginate([public(s) for s in rows])


@bp.get("/tnr/clinic-slots/<sid>")
@require_roles("ProgramCoordinator", "ClinicStaff", "Caretaker")
def get_clinic_slot(sid, user_id, role):
    return success_object(public(get_slot_or_404(sid)))


@bp.post("/tnr/clinic-days/<did>/close")
@require_roles("ClinicStaff")
def close_clinic_day(did, user_id, role):
    day = get_day_or_404(did)
    if day["status"] != "SCHEDULED":
        raise invalid_state(
            f"Clinic day is {day['status']}; only SCHEDULED days can be closed.")

    slots = [s for s in db.clinic_slots.values() if s["clinic_day_id"] == did]
    for slot in sorted(slots, key=lambda s: s["slot_index"]):
        if slot["status"] == "BOOKED":
            # No-show sweep: consume the slot only when its appointment never
            # progressed past SCHEDULED; the cat remains AT_LARGE.
            appointment = next(
                (a for a in db.appointments.values()
                 if a["clinic_slot_id"] == slot["id"] and a["status"] == "SCHEDULED"),
                None)
            if appointment is not None:
                slot["status"] = "USED"
                touch(slot)
                appointment["status"] = "NO_SHOW"
                touch(appointment)
                if appointment["voucher_id"] is not None:
                    voucher = db.vouchers.get(appointment["voucher_id"])
                    if voucher is not None and voucher["status"] == "COMMITTED":
                        voucher["status"] = "ISSUED"
                        touch(voucher)
        elif slot["status"] == "OPEN":
            slot["status"] = "RELEASED"
            touch(slot)
    # The sweep consumes booked slots without decrementing booked_count
    # (PRD §2.7): the day is closing and the count no longer gates anything.
    day["status"] = "COMPLETED"
    touch(day)
    return success_object(public(day))


@bp.post("/tnr/clinic-days/<did>/cancel")
@require_roles("ClinicStaff")
def cancel_clinic_day(did, user_id, role):
    day = get_day_or_404(did)
    if day["status"] != "SCHEDULED":
        raise invalid_state(
            f"Clinic day is {day['status']}; only SCHEDULED days can be "
            "cancelled.")
    if day["booked_count"] != 0:
        raise ApiError(ERR_DAY_HAS_BOOKINGS, 409,
                       "Clinic day cancellation requires booked_count == 0.")
    for slot in db.clinic_slots.values():
        if slot["clinic_day_id"] == did and slot["status"] == "OPEN":
            slot["status"] = "RELEASED"
            touch(slot)
    day["status"] = "CANCELLED"
    touch(day)
    return success_object(public(day))
