"""Patients (PRD 3.2)."""
from flask import Blueprint

import db
import errors
import helpers
import response
from middleware import require

bp = Blueprint("patients", __name__)


@bp.post("/patients")
@require("FrontDesk", "PracticeAdmin")
def create_patient():
    data = helpers.body()
    full_name = helpers.require_str(data, "full_name")
    dob = helpers.require_str(data, "date_of_birth")
    coins = helpers.opt_number(data, "insurance_coinsurance_rate", 0.2)
    if coins < 0 or coins > 1:
        raise errors.invalid_request("insurance_coinsurance_rate must be between 0 and 1")
    ded = helpers.opt_int(data, "insurance_deductible_remaining_cents", 0)
    if ded < 0:
        raise errors.invalid_request("insurance_deductible_remaining_cents must be >= 0")
    row = {
        "full_name": full_name,
        "date_of_birth": dob,
        "has_active_insurance": helpers.opt_bool(data, "has_active_insurance", False),
        "insurance_coinsurance_rate": coins,
        "insurance_deductible_remaining_cents": ded,
        "last_skin_check_at": None,
    }
    db.stamp_new(row)
    db.patients[row["id"]] = row
    return response.created(row)


@bp.get("/patients/<pid>")
@require("FrontDesk", "PracticeAdmin", "Provider", "BillingSpecialist")
def get_patient(pid):
    row = helpers.get_or_404(db.patients, pid, "patient")
    return response.ok(row)


@bp.get("/patients")
@require("FrontDesk", "PracticeAdmin", "Provider", "BillingSpecialist")
def list_patients():
    page, limit, offset, total = helpers.paginate(list(db.patients.values()))
    return response.listing(page, limit, offset, total)
