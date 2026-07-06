"""Patients, Physicians, Suppliers (PRD §3.1)."""
import re

from flask import Blueprint

from db import db, base_common_fields
from errors import ApiError
from middleware import get_auth, require_roles
from response import ok_object
from validation import get_json_body, require_str, require_enum, lookup
from clock import is_valid_date
from serializers import patient_out, physician_out, supplier_out

bp = Blueprint("onboarding", __name__)

PAYER_TYPES = {"MEDICARE", "MEDICAID", "COMMERCIAL", "SELF_PAY"}
_NPI_RE = re.compile(r"^\d{10}$")


# ---- Patients ----
@bp.route("/op/patients", methods=["POST"])
def create_patient():
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist", "ComplianceOfficer"})
    body = get_json_body()

    full_name = require_str(body, "full_name")
    dob = require_str(body, "date_of_birth")
    if not is_valid_date(dob):
        raise ApiError("ERR_INVALID_REQUEST", "date_of_birth must be YYYY-MM-DD.")
    payer_type = require_enum(body, "payer_type", PAYER_TYPES)

    mbi = body.get("medicare_beneficiary_id")
    if mbi is not None and not isinstance(mbi, str):
        raise ApiError("ERR_INVALID_REQUEST", "medicare_beneficiary_id must be a string or null.")

    k_level = body.get("functional_k_level")
    if k_level is not None:
        if isinstance(k_level, bool) or not isinstance(k_level, int) or k_level < 0 or k_level > 4:
            raise ApiError("ERR_INVALID_REQUEST", "functional_k_level must be an integer 0..4 or null.")

    patient = base_common_fields()
    patient.update({
        "full_name": full_name,
        "date_of_birth": dob,
        "payer_type": payer_type,
        "medicare_beneficiary_id": mbi,
        "functional_k_level": k_level,
    })
    db.patients[patient["id"]] = patient
    return ok_object(patient_out(patient), 201)


@bp.route("/op/patients/<rid>", methods=["GET"])
def get_patient(rid):
    _, role = get_auth()
    require_roles(role, {"BillingSpecialist", "ComplianceOfficer", "Practitioner"})
    patient = lookup(db.patients, rid)
    return ok_object(patient_out(patient), 200)


# ---- Physicians ----
@bp.route("/op/physicians", methods=["POST"])
def create_physician():
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer"})
    body = get_json_body()

    full_name = require_str(body, "full_name")
    npi = require_str(body, "npi")
    if not _NPI_RE.match(npi):
        raise ApiError("ERR_INVALID_REQUEST", "npi must be exactly 10 digits.")

    pecos = body.get("pecos_enrolled", False)
    if pecos is None:
        pecos = False
    if not isinstance(pecos, bool):
        raise ApiError("ERR_INVALID_REQUEST", "pecos_enrolled must be a boolean.")

    phys = base_common_fields()
    phys.update({"full_name": full_name, "npi": npi, "pecos_enrolled": pecos})
    db.physicians[phys["id"]] = phys
    return ok_object(physician_out(phys), 201)


@bp.route("/op/physicians/<rid>", methods=["GET"])
def get_physician(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer", "BillingSpecialist", "Practitioner", "Physician"})
    phys = lookup(db.physicians, rid)
    return ok_object(physician_out(phys), 200)


# ---- Suppliers ----
@bp.route("/op/suppliers", methods=["POST"])
def create_supplier():
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer"})
    body = get_json_body()

    legal_name = require_str(body, "legal_name")

    expiry = body.get("accreditation_expiry")
    if expiry is not None and not isinstance(expiry, str):
        raise ApiError("ERR_INVALID_REQUEST", "accreditation_expiry must be an ISO 8601 string or null.")

    surety = body.get("surety_bond_active", False)
    if surety is None:
        surety = False
    if not isinstance(surety, bool):
        raise ApiError("ERR_INVALID_REQUEST", "surety_bond_active must be a boolean.")

    supplier = base_common_fields()
    supplier.update({
        "legal_name": legal_name,
        "accreditation_expiry": expiry,
        "surety_bond_active": surety,
    })
    db.suppliers[supplier["id"]] = supplier
    return ok_object(supplier_out(supplier, db.current_utc), 201)


@bp.route("/op/suppliers/<rid>", methods=["GET"])
def get_supplier(rid):
    _, role = get_auth()
    require_roles(role, {"ComplianceOfficer", "BillingSpecialist", "Practitioner"})
    supplier = lookup(db.suppliers, rid)
    return ok_object(supplier_out(supplier, db.current_utc), 200)
