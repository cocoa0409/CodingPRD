"""Patient routes (scaffold §1.5 — Patients block; PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_VETERAN_FLAG_REQUIRED
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    require_bool,
    require_date,
    require_enum,
    require_fields,
    require_string,
    lookup_or_404,
)


bp = Blueprint("patients", __name__)

INSURANCE_TYPES = {"MEDICARE", "COMMERCIAL", "MEDICAID", "VA_TRICARE", "SELF_PAY"}
PATIENT_STATUSES = {"ACTIVE", "DISCHARGED", "INACTIVE"}


@bp.post("/rehab/patients")
def create_patient():
    require_auth(["PlatformAdmin", "CaseManager"])()
    body = get_json_body()
    require_fields(body, ["full_name", "date_of_birth", "insurance_type"])

    full_name = require_string(body["full_name"], "full_name", max_len=120)
    dob = require_date(body["date_of_birth"], "date_of_birth")
    insurance_type = require_enum(body["insurance_type"], INSURANCE_TYPES, "insurance_type")
    is_veteran = body.get("is_veteran", False)
    if is_veteran is None:
        is_veteran = False
    is_veteran = require_bool(is_veteran, "is_veteran")

    # PRD §3.1 / §1.4 priority 460: VA_TRICARE requires is_veteran=true.
    if insurance_type == "VA_TRICARE" and not is_veteran:
        raise APIError(
            ERR_VETERAN_FLAG_REQUIRED,
            422,
            "Patient.insurance_type=VA_TRICARE requires is_veteran=true",
        )

    with db.mutation_lock:
        patient = {
            "full_name": full_name,
            "date_of_birth": dob.isoformat(),
            "insurance_type": insurance_type,
            "is_veteran": is_veteran,
            "status": "ACTIVE",
        }
        db.stamp_common(patient)
        db.patients[patient["id"]] = patient
        return ok_object(patient, 201)


@bp.get("/rehab/patients/<pid>")
def get_patient(pid: str):
    require_auth(
        ["PlatformAdmin", "CaseManager", "Therapist", "BillingClerk", "VAReferralCoordinator"]
    )()
    patient = lookup_or_404(db.patients, pid, "Patient")
    return ok_object(patient, 200)


@bp.get("/rehab/patients")
def list_patients():
    require_auth(["PlatformAdmin", "CaseManager"])()
    limit, offset = paginate_params(request.args)

    items = list(db.patients.values())
    if "status" in request.args:
        items = [p for p in items if p["status"] == request.args.get("status")]
    if "insurance_type" in request.args:
        items = [p for p in items if p["insurance_type"] == request.args.get("insurance_type")]
    if "is_veteran" in request.args:
        flag = request.args.get("is_veteran") == "true"
        items = [p for p in items if p["is_veteran"] == flag]
    items.sort(key=db.created_then_id)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
