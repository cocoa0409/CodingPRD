"""Patient endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_PATIENT_MRN_EXISTS, ERR_PATIENT_NOT_FOUND
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public
from validate import get_body, req_date, req_str, opt_str

bp = Blueprint("patients", __name__)


@bp.post("/endoscopy/patients")
def create_patient():
    authorized(["SchedulingCoordinator", "UnitAdmin"])
    body = get_body()
    mrn = req_str(body, "mrn")
    full_name = req_str(body, "full_name")
    dob = req_date(body, "date_of_birth")
    contact_phone = opt_str(body, "contact_phone", None)
    # Rung 10 (uniqueness): mrn unique across patients
    for p in db["patients"].values():
        if p["mrn"] == mrn:
            raise_error(ERR_PATIENT_MRN_EXISTS, f"duplicate mrn: {mrn}")
    rec = new_record("patients", {
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": dob.isoformat(),
        "contact_phone": contact_phone,
    })
    return success_object(public(rec), status=201)


@bp.get("/endoscopy/patients")
def list_patients():
    return list_response("patients", {"mrn": request.args.get("mrn")})


@bp.get("/endoscopy/patients/<rid>")
def get_patient(rid):
    return get_one("patients", rid, ERR_PATIENT_NOT_FOUND)
