"""Patient endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import (
    ROLE_BILLER,
    ROLE_CLINIC_ADMIN,
    ROLE_PATIENT,
    ROLE_THERAPIST,
    require_roles,
)
from ..errors import err_forbidden, err_validation
from ..helpers import assert_enum, assert_string, require_json_object
from ..responses import created, ok
from ..services.constants import CAP_HARD_CENTS, KX_THRESHOLD_CENTS
from ..services.lookups import get_patient_or_404
from ..services.mutations import create_patient
from ..services.serialize import patient_to_dict
from ..store import store

bp = Blueprint("patients", __name__)

INSURANCE_TYPES = ["MEDICARE_PART_B", "VA", "COMMERCIAL", "SELF_PAY"]


@bp.route("/patients", methods=["POST"])
@require_roles(ROLE_CLINIC_ADMIN)
def create_patient_route(**_kwargs):
    body = require_json_object()
    full_name = assert_string(body.get("full_name"), "full_name")
    date_of_birth = assert_string(body.get("date_of_birth"), "date_of_birth")
    insurance_type = assert_enum(body.get("insurance_type"), "insurance_type", INSURANCE_TYPES)
    mbi = body.get("medicare_beneficiary_id")
    var = body.get("va_referral_id")
    if insurance_type == "MEDICARE_PART_B":
        if not mbi or not isinstance(mbi, str):
            raise err_validation("medicare_beneficiary_id is required when insurance_type is MEDICARE_PART_B")
    if insurance_type == "VA":
        if not var or not isinstance(var, str):
            raise err_validation("va_referral_id is required when insurance_type is VA")
    if mbi is not None and not isinstance(mbi, str):
        raise err_validation("medicare_beneficiary_id must be a string")
    if var is not None and not isinstance(var, str):
        raise err_validation("va_referral_id must be a string")
    s = store()
    with s.lock:
        row = create_patient(full_name, date_of_birth, insurance_type, mbi, var)
    return created(patient_to_dict(row))


@bp.route("/patients/<pid>", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER, ROLE_PATIENT)
def get_patient_route(pid: str, *, _caller_id: str, _caller_role: str):
    s = store()
    with s.lock:
        row = get_patient_or_404(pid)
        # Patient role may only read its own row
        if _caller_role == ROLE_PATIENT and row["id"] != _caller_id:
            raise err_forbidden("Patient may only read their own record")
    return ok(patient_to_dict(row))


@bp.route("/patients/<pid>/cap-status", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN, ROLE_THERAPIST, ROLE_BILLER)
def get_cap_status(pid: str, **_kwargs):
    s = store()
    with s.lock:
        patient = get_patient_or_404(pid)
        ytd = patient.get("ytd_capped_amount_cents", 0)
        result = {
            "ytd_capped_amount_cents": ytd,
            "remaining_to_threshold_cents": max(0, KX_THRESHOLD_CENTS - ytd),
            "remaining_to_hard_cap_cents": max(0, CAP_HARD_CENTS - ytd),
            "kx_required": ytd > KX_THRESHOLD_CENTS,
        }
    return ok(result)
