"""Patient endpoints (PRD §3.1)."""
import re

from flask import Blueprint

from db import db
from errors import err
from middleware import get_auth, require_roles
from models import base_record, serialize
from response import object_response
from services.store import get_patient
from services.minor import is_minor_for_case
from validation import get_body, require_str

bp = Blueprint("patients", __name__)

_STATE_RE = re.compile(r"^[A-Z]{2}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _serialize_patient(rec):
    out = serialize(rec)
    # is_minor_at_intake is computed from DOB vs the patient's cases' intake
    # captures; true if a minor at any case's earliest intake (PRD §3.1).
    minor = False
    for case in db.cases.values():
        if case["patient_id"] == rec["id"] and is_minor_for_case(case):
            minor = True
            break
    out["is_minor_at_intake"] = minor
    return out


@bp.route("/patients", methods=["POST"])
def create_patient():
    _, role = get_auth()
    require_roles(role, {"Patient", "BillingAdmin"})
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    state_code = require_str(body, "state_code")
    date_of_birth = require_str(body, "date_of_birth")

    if not _STATE_RE.match(state_code):
        raise err("ERR_INVALID_REQUEST", "state_code must be two uppercase letters.")
    if not _DATE_RE.match(date_of_birth):
        raise err("ERR_INVALID_REQUEST", "date_of_birth must be an ISO date (YYYY-MM-DD).")
    # email uniqueness
    for p in db.patients.values():
        if p["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique across patients.")

    rec = base_record(common_fields=True)
    rec.update({
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
        "date_of_birth": date_of_birth,
        "is_minor_at_intake": False,
    })
    db.patients[rec["id"]] = rec
    return object_response(_serialize_patient(rec), status=201)


@bp.route("/patients/<pid>", methods=["GET"])
def fetch_patient(pid):
    _, role = get_auth()
    require_roles(role, {"Patient", "Clinician", "BillingAdmin", "ManufacturingOps"})
    rec = get_patient(pid)
    return object_response(_serialize_patient(rec), status=200)
