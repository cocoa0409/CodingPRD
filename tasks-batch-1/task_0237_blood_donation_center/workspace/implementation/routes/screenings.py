"""Health screenings: record (computes PASS/FAIL, auto-defers), reads."""
from flask import Blueprint, request

import db
import lookup
from common import (
    get_json_body,
    paginate,
    require_bool,
    require_integer,
    require_number,
    require_string,
)
from middleware import require_roles
from response import success, success_list
from services import domain
from services.serialize import serialize_screening

bp = Blueprint("screenings", __name__)


@bp.route("/blood-bank/health-screenings", methods=["POST"])
@require_roles("IntakeNurse")
def create_screening():
    body = get_json_body()
    with db.lock:
        appointment_id = require_string(body, "appointment_id")
        hemoglobin = require_number(body, "hemoglobin_g_dl")
        systolic = require_integer(body, "systolic_bp")
        pulse = require_integer(body, "pulse_bpm")
        weight = require_number(body, "weight_kg")
        travel = require_bool(body, "recent_travel_risk")
        medication = require_bool(body, "disqualifying_medication")

        appt = lookup.appointment(appointment_id)
        donor = db.donors.get(appt["donor_id"])
        center = db.centers.get(appt["center_id"])

        outcome, failure_reason = domain.compute_screening_outcome(
            hemoglobin, weight, systolic, pulse, travel, medication)

        screening = {
            "appointment_id": appointment_id,
            "donor_id": appt["donor_id"],
            "hemoglobin_g_dl": hemoglobin,
            "systolic_bp": systolic,
            "pulse_bpm": pulse,
            "weight_kg": weight,
            "recent_travel_risk": travel,
            "disqualifying_medication": medication,
            "outcome": outcome,
            "failure_reason": failure_reason,
        }
        db.stamp_new(screening)
        db.screenings[screening["id"]] = screening

        # conditional auto-deferral on certain failure reasons
        if outcome == "FAIL" and failure_reason in ("HEMOGLOBIN_LOW", "TRAVEL_RISK", "MEDICATION"):
            if failure_reason == "HEMOGLOBIN_LOW":
                category, days = "HEMOGLOBIN", domain.HEMOGLOBIN_DEFERRAL_DAYS
            elif failure_reason == "TRAVEL_RISK":
                category, days = "TRAVEL", domain.TRAVEL_DEFERRAL_DAYS
            else:
                category, days = "MEDICATION", domain.MED_DEFERRAL_DAYS
            domain.create_deferral(
                donor, center, category, "TEMPORARY",
                "Auto-deferral from screening %s" % failure_reason,
                duration_days=days,
            )

        return success(serialize_screening(screening), status=201)


@bp.route("/blood-bank/health-screenings", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician")
def list_screenings():
    appointment_id = request.args.get("appointment_id")
    donor_id = request.args.get("donor_id")
    outcome = request.args.get("outcome")
    with db.lock:
        rows = list(db.screenings.values())
        if appointment_id is not None:
            rows = [s for s in rows if s["appointment_id"] == appointment_id]
        if donor_id is not None:
            rows = [s for s in rows if s["donor_id"] == donor_id]
        if outcome is not None:
            rows = [s for s in rows if s["outcome"] == outcome]
        page, limit, offset, total = paginate(rows)
        return success_list([serialize_screening(s) for s in page], limit, offset, total)


@bp.route("/blood-bank/health-screenings/<screening_id>", methods=["GET"])
@require_roles("CenterAdmin", "IntakeNurse", "LabTechnician")
def get_screening(screening_id):
    with db.lock:
        screening = lookup.screening(screening_id)
        return success(serialize_screening(screening))
