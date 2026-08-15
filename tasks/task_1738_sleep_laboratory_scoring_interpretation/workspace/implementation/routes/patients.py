"""Patient registration (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_DUPLICATE_MRN
from middleware import authorized
from response import success_object
from routes.helpers import get_one, public
from services.core import new_record
from validate import get_body, req_date, req_str

bp = Blueprint("patients", __name__)


@bp.post("/patients")
def create_patient():
    authorized(["Scheduler"])
    body = get_body()
    mrn = req_str(body, "mrn")
    full_name = req_str(body, "full_name")
    dob = req_date(body, "date_of_birth")
    for existing in db["patients"].values():
        if existing["mrn"] == mrn:
            raise_error(ERR_DUPLICATE_MRN, f"mrn already registered: {mrn}")
    rec = new_record("patients", {
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": dob,
    })
    return success_object(public(rec), status=201)


@bp.get("/patients/<patientId>")
def get_patient(patientId):
    return get_one("patients", patientId)
