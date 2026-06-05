"""Patient CRUD + list-orders endpoint."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_DUPLICATE_IDENTIFIER, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields, require_string, require_pattern, lookup_or_404,
    MRN_PATTERN,
)
from services.calculations import compute_age_band


bp = Blueprint("patients", __name__)


# ---------- POST /patients --------------------------------------------------

@bp.post("/patients")
def create_patient():
    require_auth(["LabTech", "LabDirector"])()
    body = get_json_body()
    require_fields(body, ["mrn", "full_name", "date_of_birth"])
    mrn = body["mrn"]
    full_name = body["full_name"]
    dob = body["date_of_birth"]

    require_string(mrn, "mrn")
    require_pattern(mrn, MRN_PATTERN, "mrn")
    require_string(full_name, "full_name", min_len=1, max_len=500)
    require_string(dob, "date_of_birth")
    try:
        db.parse_iso_date(dob)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "date_of_birth must be ISO 8601 YYYY-MM-DD")

    # Uniqueness on mrn.
    for p in db.patients.values():
        if p.get("mrn") == mrn:
            raise APIError(ERR_DUPLICATE_IDENTIFIER, 409,
                           f"Patient with mrn '{mrn}' already exists")

    age_band = compute_age_band(dob, db.get_current_utc_dt())
    patient = {
        "mrn": mrn,
        "full_name": full_name,
        "date_of_birth": dob,
        "age_band": age_band,
        "results_release_count": 0,
        "critical_incidents_count": 0,
    }
    db.stamp_common(patient)
    db.patients[patient["id"]] = patient
    return ok_object(patient, http_status=201)


# ---------- GET /patients/{id} ---------------------------------------------

@bp.get("/patients/<pid>")
def get_patient(pid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider", "Phlebotomist"])()
    p = lookup_or_404(db.patients, pid, "Patient")
    return ok_object(p)


# ---------- GET /patients ---------------------------------------------------

@bp.get("/patients")
def list_patients():
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    limit, offset = paginate_params(request.args)
    mrn = request.args.get("mrn")
    items = list(db.patients.values())
    if mrn is not None:
        items = [p for p in items if p.get("mrn") == mrn]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------- GET /patients/{id}/lab-orders ----------------------------------

@bp.get("/patients/<pid>/lab-orders")
def list_patient_lab_orders(pid):
    require_auth(["LabTech", "LabDirector", "OrderingProvider"])()
    lookup_or_404(db.patients, pid, "Patient")
    limit, offset = paginate_params(request.args)
    status = request.args.get("status")
    items = [o for o in db.lab_orders.values() if o.get("patient_id") == pid]
    if status is not None:
        items = [o for o in items if o.get("status") == status]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)
