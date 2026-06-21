"""Appointments: book (OCC), reads, check-in, cancel, no-show, collection."""
from flask import Blueprint, request

import db
import errors
import lookup
from common import (
    get_json_body,
    paginate,
    require_integer,
    require_string,
)
from errors import ApiError
from middleware import require_roles
from response import success, success_list
from routes.slots import recompute_slot_status
from services import domain
from services.serialize import serialize_appointment, serialize_donation
from timeutil import iso_to_epoch

bp = Blueprint("appointments", __name__)


def _release_slot_seat(slot):
    """Appointment left the SCHEDULED/CHECKED_IN set: free one seat."""
    if slot is not None:
        slot["booked_count"] = max(0, slot["booked_count"] - 1)
        recompute_slot_status(slot)
        db.touch(slot)


@bp.route("/blood-bank/appointments", methods=["POST"])
@require_roles("Donor", "IntakeNurse")
def book_appointment():
    body = get_json_body()
    with db.lock:
        donor_id = require_string(body, "donor_id")
        slot_id = require_string(body, "slot_id")
        expected_slot_version = require_integer(body, "expected_slot_version")
        # existence: body FKs in declared order (donor_id, slot_id)
        donor = lookup.donor(donor_id)
        slot = lookup.slot(slot_id)

        # OCC (priority 5) BEFORE any capacity/state business check
        if expected_slot_version != slot["version"]:
            raise ApiError(errors.ERR_STALE_SLOT_VERSION, 412,
                           "expected_slot_version does not match the slot version.")

        # state (priority 6): slot bookable
        if slot["status"] in ("CLOSED", "FULL"):
            raise ApiError(errors.ERR_SLOT_NOT_BOOKABLE, 409,
                           "Slot is CLOSED or FULL.")

        # business constraint (priority 13): at most one open appointment
        if domain.open_appointment_for(donor_id) is not None:
            raise ApiError(errors.ERR_DONOR_HAS_OPEN_APPOINTMENT, 409,
                           "Donor already holds an open appointment.")

        center = db.centers.get(slot["center_id"])
        appt = {
            "donor_id": donor_id,
            "slot_id": slot_id,
            "center_id": slot["center_id"],
            "donation_type": slot["donation_type"],
            "status": "SCHEDULED",
            "booked_at": center["current_utc"],
        }
        db.stamp_new(appt)
        db.appointments[appt["id"]] = appt

        slot["booked_count"] += 1
        recompute_slot_status(slot)
        db.touch(slot)  # version += 1

        domain.recompute_pending_donation_type(donor)
        db.touch(donor)
        return success(serialize_appointment(appt), status=201)


@bp.route("/blood-bank/appointments", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager", "Donor")
def list_appointments():
    donor_id = request.args.get("donor_id")
    slot_id = request.args.get("slot_id")
    center_id = request.args.get("center_id")
    status = request.args.get("status")
    with db.lock:
        rows = list(db.appointments.values())
        if donor_id is not None:
            rows = [a for a in rows if a["donor_id"] == donor_id]
        if slot_id is not None:
            rows = [a for a in rows if a["slot_id"] == slot_id]
        if center_id is not None:
            rows = [a for a in rows if a["center_id"] == center_id]
        if status is not None:
            rows = [a for a in rows if a["status"] == status]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_appointment(a) for a in page], limit, offset, total)


@bp.route("/blood-bank/appointments/<appointment_id>", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician", "InventoryManager", "Donor")
def get_appointment(appointment_id):
    with db.lock:
        appt = lookup.appointment(appointment_id)
        return success(serialize_appointment(appt))


@bp.route("/blood-bank/appointments/<appointment_id>/check-in", methods=["POST"])
@require_roles("IntakeNurse")
def check_in(appointment_id):
    with db.lock:
        appt = lookup.appointment(appointment_id)
        donor = db.donors.get(appt["donor_id"])
        center = db.centers.get(appt["center_id"])

        # precondition 1 (state): appointment SCHEDULED
        if appt["status"] != "SCHEDULED":
            raise ApiError(errors.ERR_APPOINTMENT_NOT_SCHEDULED, 409,
                           "Appointment must be SCHEDULED to check in.")
        # precondition 2 (eligibility): donor ELIGIBLE at current_utc
        domain.recompute_donor(donor, center)
        if donor["eligibility_status"] != "ELIGIBLE":
            raise ApiError(errors.ERR_DONOR_NOT_ELIGIBLE, 403,
                           "Donor is not ELIGIBLE.")
        # precondition 3 (interval): FINAL inter-donation interval elapsed
        if not domain.interval_elapsed(donor, appt["donation_type"], center):
            raise ApiError(errors.ERR_INTERVAL_NOT_ELAPSED, 409,
                           "Inter-donation interval has not elapsed.")

        appt["status"] = "CHECKED_IN"
        db.touch(appt)
        return success(serialize_appointment(appt))


@bp.route("/blood-bank/appointments/<appointment_id>/cancel", methods=["POST"])
@require_roles("Donor", "IntakeNurse")
def cancel_appointment(appointment_id):
    with db.lock:
        appt = lookup.appointment(appointment_id)
        if appt["status"] != "SCHEDULED":
            raise ApiError(errors.ERR_APPOINTMENT_NOT_CANCELLABLE, 409,
                           "Appointment must be SCHEDULED to cancel.")
        appt["status"] = "CANCELLED"
        db.touch(appt)
        _release_slot_seat(db.slots.get(appt["slot_id"]))
        donor = db.donors.get(appt["donor_id"])
        if donor is not None:
            domain.recompute_pending_donation_type(donor)
            db.touch(donor)
        return success(serialize_appointment(appt))


@bp.route("/blood-bank/appointments/<appointment_id>/no-show", methods=["POST"])
@require_roles("IntakeNurse")
def no_show(appointment_id):
    with db.lock:
        appt = lookup.appointment(appointment_id)
        center = db.centers.get(appt["center_id"])
        # state: appointment CHECKED_IN
        if appt["status"] != "CHECKED_IN":
            raise ApiError(errors.ERR_APPOINTMENT_NOT_CHECKED_IN, 409,
                           "Appointment must be CHECKED_IN to mark no-show.")
        # temporal: slot window must have ended
        slot = db.slots.get(appt["slot_id"])
        if iso_to_epoch(center["current_utc"]) < iso_to_epoch(slot["ends_at"]):
            raise ApiError(errors.ERR_SLOT_WINDOW_OPEN, 409,
                           "Slot window has not ended yet.")
        appt["status"] = "NO_SHOW"
        db.touch(appt)
        _release_slot_seat(slot)
        donor = db.donors.get(appt["donor_id"])
        if donor is not None:
            domain.recompute_pending_donation_type(donor)
            db.touch(donor)
        return success(serialize_appointment(appt))


@bp.route("/blood-bank/appointments/<appointment_id>/donations", methods=["POST"])
@require_roles("IntakeNurse")
def record_collection(appointment_id):
    body = get_json_body()
    with db.lock:
        appt = lookup.appointment(appointment_id)
        center = db.centers.get(appt["center_id"])
        donor = db.donors.get(appt["donor_id"])
        volume_ml = require_integer(body, "volume_ml", minimum=1)

        # state: appointment CHECKED_IN
        if appt["status"] != "CHECKED_IN":
            raise ApiError(errors.ERR_APPOINTMENT_NOT_CHECKED_IN, 409,
                           "Appointment must be CHECKED_IN to record a collection.")
        # business safety: a PASS screening must exist for this appointment
        pass_screening = None
        for s in db.screenings.values():
            if s["appointment_id"] == appointment_id and s["outcome"] == "PASS":
                pass_screening = s
                break
        if pass_screening is None:
            raise ApiError(errors.ERR_SCREENING_NOT_PASSED, 409,
                           "A PASS health screening is required before collection.")

        donation_type = appt["donation_type"]
        if donation_type == "PLASMA":
            # governing weight: passing screening's weight_kg, else donor.weight_kg
            governing_weight = pass_screening.get("weight_kg")
            if governing_weight is None:
                governing_weight = donor.get("weight_kg")
            # per-collection band cap (422)
            band_cap = domain.plasma_band_cap(governing_weight)
            if volume_ml > band_cap:
                raise ApiError(errors.ERR_PLASMA_VOLUME_EXCEEDED, 422,
                               "PLASMA volume exceeds the weight-band cap.")
            # rolling annual cap (422)
            annual = domain.rolling_annual_plasma_liters(donor["id"], center, volume_ml)
            if annual > domain.ANNUAL_PLASMA_LITERS_CAP:
                raise ApiError(errors.ERR_ANNUAL_PLASMA_CAP_EXCEEDED, 422,
                               "Rolling annual plasma volume exceeds the cap.")

        # commit: complete appointment, create donation
        appt["status"] = "COMPLETED"
        db.touch(appt)

        donation = {
            "appointment_id": appointment_id,
            "donor_id": appt["donor_id"],
            "center_id": appt["center_id"],
            "donation_type": donation_type,
            "volume_ml": volume_ml,
            "collected_at": center["current_utc"],
            "status": "COLLECTED",
            "test_result_id": None,
        }
        db.stamp_new(donation)
        db.donations[donation["id"]] = donation

        _release_slot_seat(db.slots.get(appt["slot_id"]))
        domain.recompute_donor(donor, center)
        return success(serialize_donation(donation), status=201)
