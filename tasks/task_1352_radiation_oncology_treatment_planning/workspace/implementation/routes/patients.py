"""Patients (PRD 3.1)."""
from flask import Blueprint

from db import store, new_entity, sorted_all
from errors import err, ERR_NOT_FOUND, ERR_DUPLICATE_MRN
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import patient_json
from timeutil import new_id, parse_date
from validate import req_str

bp = Blueprint("patients", __name__)


@bp.post("/oncology/patients")
@require_roles("Scheduler")
def create_patient(user_id):
    body = get_body()
    # p4 schema (before uniqueness, which is a p11 business constraint)
    mrn = req_str(body, "mrn")
    full_name = req_str(body, "full_name")
    dob = req_str(body, "date_of_birth")
    if parse_date(dob) is None:
        from errors import ERR_INVALID_REQUEST
        err(ERR_INVALID_REQUEST, "date_of_birth must be a valid calendar date (YYYY-MM-DD)")
    # p11: mrn unique across all patients
    for p in store.patients.values():
        if p["mrn"] == mrn:
            err(ERR_DUPLICATE_MRN, "A patient with the same mrn already exists")
    p = new_entity()
    p.update({"id": new_id(), "mrn": mrn, "full_name": full_name,
              "date_of_birth": dob})
    store.patients[p["id"]] = p
    return success(patient_json(p), 201)


@bp.get("/oncology/patients")
@require_roles(*ALL_ROLES)
def list_patients(user_id):
    items = sorted_all(store.patients.values())
    page, meta = paginate(items)
    return success([patient_json(p) for p in page], 200, pagination=meta)


@bp.get("/oncology/patients/<pid>")
@require_roles(*ALL_ROLES)
def get_patient(pid, user_id):
    p = store.patients.get(pid)
    if p is None:
        err(ERR_NOT_FOUND, "patient not found")
    return success(patient_json(p), 200)
