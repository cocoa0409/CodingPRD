"""Patient endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import db, lock
from helpers import (
    get_json_body, require_str, require_bool, require_fields, stamp_new,
    parse_pagination, sort_and_paginate,
)
from lookups import (
    get_or_404, fk_or_404, require_guardian_owns_patient, family_of_patient,
    guardian_owns_family,
)
from middleware import require_roles
from response import success, list_success
from serializers import public, public_list

bp = Blueprint("patients", __name__)


@bp.post("/patients")
@require_roles("FrontDesk", "ClinicAdmin")
def create_patient():
    body = get_json_body()
    family_account_id = require_str(body, "family_account_id")
    full_name = require_str(body, "full_name")
    require_fields(body, ["date_of_birth"])
    dob = body["date_of_birth"]
    if not isinstance(dob, str) or dob == "":
        from errors import invalid_request
        raise invalid_request("date_of_birth must be a non-empty string")
    is_minor = require_bool(body, "is_minor")
    with lock:
        fk_or_404(db.family_accounts, family_account_id)
        rec = {
            "family_account_id": family_account_id,
            "full_name": full_name,
            "date_of_birth": dob,
            "is_minor": is_minor,
            "records_complete": False,
        }
        stamp_new(rec)
        db.patients[rec["id"]] = rec
        return success(public(rec), 201)


@bp.get("/patients/<patient_id>")
@require_roles("FrontDesk", "ClinicAdmin", "BillingSpecialist", "Orthodontist", "Guardian")
def get_patient(patient_id):
    with lock:
        rec = get_or_404(db.patients, patient_id)
        require_guardian_owns_patient(rec)
        return success(public(rec), 200)


@bp.get("/patients")
@require_roles("FrontDesk", "ClinicAdmin", "BillingSpecialist", "Orthodontist", "Guardian")
def list_patients():
    from flask import g
    with lock:
        limit, offset = parse_pagination()
        family_account_id = request.args.get("family_account_id")
        records = list(db.patients.values())
        if family_account_id is not None:
            records = [r for r in records if r["family_account_id"] == family_account_id]
        # Guardian sees only patients in their own family.
        if g.user_role == "Guardian":
            records = [
                r for r in records
                if guardian_owns_family(family_of_patient(r))
            ]
        page, total = sort_and_paginate(records, limit, offset)
        return list_success(public_list(page), limit, offset, total, 200)
