"""Patient registration and FK reverse reachability (PRD 3.2)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_PATIENT_NOT_FOUND, ERR_DUPLICATE_MRN, ERR_INVALID_REQUEST
from middleware import authorized, check_ownership
from response import success_object
from routes.helpers import list_envelope, require
from services.core import account_view, application_view, new_record, public
from validate import get_body, opt_str, req_date, req_str

bp = Blueprint("patients", __name__)

ALL_ROLES = ["Patient", "FinancialCounselor", "AssistanceReviewer",
             "BillingAdministrator", "CollectionsAgent", "ComplianceOfficer"]


@bp.post("/charity-care/patients")
def create_patient():
    authorized(["FinancialCounselor", "ComplianceOfficer"])
    body = get_body()
    # Priority 12: mrn uniqueness
    mrn = req_str(body, "mrn")
    if any(p["mrn"] == mrn for p in db["patients"].values()):
        raise_error(ERR_DUPLICATE_MRN, "mrn already registered")
    # Priority 13: remaining fields
    full_name = req_str(body, "full_name")
    date_of_birth = req_date(body, "date_of_birth")
    ssn_last4 = req_str(body, "ssn_last4")
    if len(ssn_last4) != 4 or not ssn_last4.isdigit():
        raise_error(ERR_INVALID_REQUEST, "ssn_last4 must be exactly 4 numeric characters")
    contact_email = opt_str(body, "contact_email")
    rec = new_record("patients", {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "ssn_last4": ssn_last4,
        "mrn": mrn,
        "contact_email": contact_email,
    })
    return success_object(public(rec), status=201)


@bp.get("/charity-care/patients/<pid>")
def get_patient(pid):
    caller = authorized(ALL_ROLES)
    patient = require("patients", pid, ERR_PATIENT_NOT_FOUND)
    check_ownership(caller, patient["id"])
    return success_object(public(patient))


@bp.get("/charity-care/patients/<pid>/accounts")
def list_patient_accounts(pid):
    caller = authorized(ALL_ROLES)
    patient = require("patients", pid, ERR_PATIENT_NOT_FOUND)
    check_ownership(caller, patient["id"])
    items = [a for a in db["accounts"].values() if a["patient_id"] == pid]
    return list_envelope(items, view=account_view)


@bp.get("/charity-care/patients/<pid>/applications")
def list_patient_applications(pid):
    caller = authorized(ALL_ROLES)
    patient = require("patients", pid, ERR_PATIENT_NOT_FOUND)
    check_ownership(caller, patient["id"])
    items = [a for a in db["applications"].values() if a["patient_id"] == pid]
    return list_envelope(items, view=application_view)
