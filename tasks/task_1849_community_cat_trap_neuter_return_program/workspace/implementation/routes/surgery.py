"""Surgery records (PRD §3.4).

Recorded by ClinicStaff against a checked-in appointment. A surviving outcome
(STERILIZED / ALREADY_STERILE) moves the cat AT_CLINIC -> POST_SURGERY and
copies the recorded ear-tip / rabies markers onto the cat; a fatal outcome
(DIED_IN_SURGERY) moves the cat to DECEASED and does not copy markers. Either
way the appointment completes (TRAPPED -> COMPLETED), the slot is consumed
(BOOKED -> USED) with the day's booked_count decrementing, and a committed
voucher is REDEEMED on survival (settling the §2.8 reimbursement) or VOIDED on
mortality. The colony's derived fields are recomputed.
"""

from flask import Blueprint

from db import db
from errors import invalid_state, not_found
from middleware import json_body, require_roles
from response import paginate, success_object
from services.colony_service import recompute_colony
from services.voucher_service import settle_reimbursement
from util import (now_iso, opt_bool, public, req_bool, req_enum, req_str,
                  sorted_created, stamp_common, touch)

bp = Blueprint("surgery", __name__)

OUTCOMES = {"STERILIZED", "ALREADY_STERILE", "DIED_IN_SURGERY"}


@bp.post("/tnr/surgery-records")
@require_roles("ClinicStaff")
def create_surgery_record(user_id, role):
    body = json_body()
    appointment_id = req_str(body, "appointment_id")
    surgeon_initials = req_str(body, "surgeon_initials")
    ear_tipped = req_bool(body, "ear_tipped")
    rabies_vaccinated = req_bool(body, "rabies_vaccinated")
    complications = opt_bool(body, "complications", False)
    outcome = req_enum(body, "outcome", OUTCOMES)

    appointment = db.appointments.get(appointment_id)
    if appointment is None:
        raise not_found("appointment")

    cat = db.cats.get(appointment["cat_id"])
    if appointment["status"] != "TRAPPED":
        raise invalid_state(
            f"Appointment is {appointment['status']}; surgery requires a "
            "TRAPPED appointment.")
    if cat is None or cat["status"] != "AT_CLINIC":
        raise invalid_state("The appointment's cat must stand AT_CLINIC.")

    record = stamp_common({
        "appointment_id": appointment_id,
        "surgeon_initials": surgeon_initials,
        "ear_tipped": ear_tipped,
        "rabies_vaccinated": rabies_vaccinated,
        "complications": complications,
        "outcome": outcome,
        "performed_at": now_iso(),
    })
    db.surgery_records[record["id"]] = record

    survived = outcome in ("STERILIZED", "ALREADY_STERILE")
    if survived:
        cat["status"] = "POST_SURGERY"
        cat["ear_tipped"] = ear_tipped
        cat["vaccinated_rabies"] = rabies_vaccinated
    else:
        cat["status"] = "DECEASED"
    touch(cat)

    appointment["status"] = "COMPLETED"
    touch(appointment)

    slot = db.clinic_slots.get(appointment["clinic_slot_id"])
    day = None
    if slot is not None:
        slot["status"] = "USED"
        touch(slot)
        day = db.clinic_days.get(slot["clinic_day_id"])
        if day is not None:
            day["booked_count"] -= 1
            touch(day)

    if appointment["voucher_id"] is not None:
        voucher = db.vouchers.get(appointment["voucher_id"])
        if voucher is not None and voucher["status"] == "COMMITTED":
            if survived:
                clinic = db.partner_clinics.get(day["clinic_id"]) if day else None
                if clinic is not None:
                    settle_reimbursement(voucher, clinic)
                voucher["status"] = "REDEEMED"
            else:
                # Mortality: no reimbursement; the voucher is voided.
                voucher["status"] = "VOIDED"
            touch(voucher)

    colony = db.colonies.get(cat["colony_id"])
    if colony is not None:
        recompute_colony(colony)

    return success_object(public(record), status=201)


@bp.get("/tnr/appointments/<aid>/surgery-records")
@require_roles("ProgramCoordinator", "ClinicStaff")
def list_appointment_surgery_records(aid, user_id, role):
    if aid not in db.appointments:
        raise not_found("appointment")
    rows = [r for r in db.surgery_records.values() if r["appointment_id"] == aid]
    return paginate([public(r) for r in sorted_created(rows)])
