"""Patient routes (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

from common import (
    get_json_body,
    paginate,
    public,
    require_fields,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_patient
from middleware import get_auth, require_role
from response import success

bp = Blueprint("patients", __name__)

PAYER_MODES = ("CASH", "INSURANCE")
MEMBERSHIP_STATUSES = ("NONE", "ACTIVE", "LAPSED")


@bp.route("/patients", methods=["POST"])
def create_patient():
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    body = get_json_body()
    require_fields(body, ["full_name", "date_of_birth"])
    full_name = require_string(body, "full_name")
    date_of_birth = require_string(body, "date_of_birth")

    payer_mode = body.get("payer_mode", "CASH")
    if payer_mode is None:
        payer_mode = "CASH"
    if payer_mode not in PAYER_MODES:
        raise err("ERR_INVALID_REQUEST", "payer_mode must be CASH or INSURANCE.")

    insurance_member_id = body.get("insurance_member_id")
    if insurance_member_id is not None and not isinstance(insurance_member_id, str):
        raise err("ERR_INVALID_REQUEST", "insurance_member_id must be a string.")

    coinsurance_rate = body.get("coinsurance_rate")
    if coinsurance_rate is None:
        coinsurance_rate = 0.0
    if isinstance(coinsurance_rate, bool) or not isinstance(coinsurance_rate, (int, float)):
        raise err("ERR_INVALID_REQUEST", "coinsurance_rate must be a number.")
    if Decimal(str(coinsurance_rate)) < 0 or Decimal(str(coinsurance_rate)) > 1:
        raise err("ERR_INVALID_REQUEST", "coinsurance_rate must be within [0, 1].")

    # For cash patients insurance_member_id is null.
    if payer_mode == "CASH":
        insurance_member_id = insurance_member_id  # may be supplied; left as-is or null

    rec = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "payer_mode": payer_mode,
        "insurance_member_id": insurance_member_id,
        "coinsurance_rate": coinsurance_rate,
        "intake_status": "PENDING_INTAKE",
        "membership_status": "NONE",
        "strike_count": 0,
    }
    stamp_new(rec)
    db.patients[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/patients", methods=["GET"])
def list_patients():
    _, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner"])
    data, pg = paginate(list(db.patients.values()), public)
    return success(data, status=200, pagination=pg)


@bp.route("/patients/<rid>", methods=["GET"])
def get_patient_route(rid):
    user_id, role = get_auth()
    require_role(role, ["ClinicAdmin", "Practitioner", "Patient"])
    rec = get_patient(rid)
    # Ownership: a Patient may read only their own record.
    if role == "Patient" and user_id != rec["id"]:
        raise err("ERR_OWNERSHIP_MISMATCH", "Patient may read only their own record.")
    return success(public(rec), status=200)


@bp.route("/patients/<rid>/membership", methods=["POST"])
def set_membership(rid):
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    rec = get_patient(rid)
    body = get_json_body()
    require_fields(body, ["membership_status"])
    status = body.get("membership_status")
    if status not in MEMBERSHIP_STATUSES:
        raise err("ERR_INVALID_REQUEST", "membership_status must be NONE, ACTIVE, or LAPSED.")
    rec["membership_status"] = status
    touch(rec)
    return success(public(rec), status=200)
