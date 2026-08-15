"""Patients and eligibility screenings (PRD §3.6)."""

from flask import Blueprint, request

import db
from middleware import get_auth, ROLE_COMPLIANCE_AUDITOR, ROLE_VACCINE_MANAGER
from response import success_object, paginate
from services.validate import (
    require_body, require_string, require_enum, require_date, get_or_404,
    ENUM_INSURANCE_CATEGORY, VFC_ELIGIBLE_CATEGORIES,
)

bp = Blueprint("patients_screenings", __name__)

PATIENT_ROLES = [ROLE_COMPLIANCE_AUDITOR, ROLE_VACCINE_MANAGER]


def serialize_patient(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "provider_site_id": p["provider_site_id"],
        "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "insurance_category": p["insurance_category"],
        "is_active": p["is_active"],
    }


def serialize_screening(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "patient_id": s["patient_id"],
        "screening_date": s["screening_date"],
        "screened_by_user_id": s["screened_by_user_id"],
        "insurance_category_at_visit": s["insurance_category_at_visit"],
        "vfc_eligible": s["vfc_eligible"],
        "outcome": s["outcome"],
    }


@bp.route("/provider-sites/<site_id>/patients", methods=["POST"])
def create_patient(site_id):
    get_auth([ROLE_VACCINE_MANAGER])
    site = get_or_404(db.provider_sites, site_id, "provider site")
    body = require_body(request.get_json(silent=True))
    full_name = require_string(body, "full_name")
    dob_raw, dob_date = require_date(body, "date_of_birth")
    insurance_category = require_enum(body, "insurance_category", ENUM_INSURANCE_CATEGORY)
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        from errors import invalid_request
        raise invalid_request("Field is_active must be a boolean")

    now = db.now_ts()
    patient = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "provider_site_id": site["id"],
        "full_name": full_name,
        "date_of_birth": dob_raw,
        "_dob_date": dob_date,
        "insurance_category": insurance_category,
        "is_active": is_active,
    }
    db.patients[patient["id"]] = patient
    return success_object(serialize_patient(patient), 201)


def _parse_bool_query(raw):
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


@bp.route("/provider-sites/<site_id>/patients", methods=["GET"])
def list_patients(site_id):
    get_auth(PATIENT_ROLES)
    site = get_or_404(db.provider_sites, site_id, "provider site")
    items = [p for p in db.patients.values() if p["provider_site_id"] == site["id"]]
    active = _parse_bool_query(request.args.get("is_active"))
    if active is not None:
        items = [p for p in items if p["is_active"] == active]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    return paginate([serialize_patient(p) for p in items], request.args)


@bp.route("/patients/<patient_id>", methods=["GET"])
def get_patient(patient_id):
    get_auth(PATIENT_ROLES)
    patient = get_or_404(db.patients, patient_id, "patient")
    return success_object(serialize_patient(patient))


@bp.route("/patients", methods=["GET"])
def list_patients_global():
    get_auth(PATIENT_ROLES)
    items = list(db.patients.values())
    site_filter = request.args.get("provider_site_id")
    active = _parse_bool_query(request.args.get("is_active"))
    if site_filter is not None:
        items = [p for p in items if p["provider_site_id"] == site_filter]
    if active is not None:
        items = [p for p in items if p["is_active"] == active]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    return paginate([serialize_patient(p) for p in items], request.args)


# ------------------------- Eligibility Screenings --------------------------

@bp.route("/patients/<patient_id>/eligibility-screenings", methods=["POST"])
def create_screening(patient_id):
    user_id = get_auth([ROLE_VACCINE_MANAGER])
    patient = get_or_404(db.patients, patient_id, "patient")
    body = require_body(request.get_json(silent=True))
    screening_date_raw, screening_date = require_date(body, "screening_date")
    insurance_category_at_visit = require_enum(
        body, "insurance_category_at_visit", ENUM_INSURANCE_CATEGORY
    )

    # vfc_eligibility_determination per SCAFFOLD §1.3 / PRD §3.6
    age = db.age_years_on(patient["_dob_date"], screening_date)
    categorical_ok = insurance_category_at_visit in VFC_ELIGIBLE_CATEGORIES
    age_ok = age < 19
    vfc_eligible = categorical_ok and age_ok
    outcome = "VFC_ELIGIBLE" if vfc_eligible else "PRIVATE_ONLY"

    now = db.now_ts()
    screening = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "patient_id": patient["id"],
        "screening_date": screening_date_raw,
        "screened_by_user_id": user_id,
        "insurance_category_at_visit": insurance_category_at_visit,
        "vfc_eligible": vfc_eligible,
        "outcome": outcome,
    }
    db.eligibility_screenings[screening["id"]] = screening
    return success_object(serialize_screening(screening), 201)


@bp.route("/patients/<patient_id>/eligibility-screenings", methods=["GET"])
def list_screenings(patient_id):
    get_auth(PATIENT_ROLES)
    patient = get_or_404(db.patients, patient_id, "patient")
    items = [s for s in db.eligibility_screenings.values() if s["patient_id"] == patient["id"]]
    date_filter = request.args.get("screening_date")
    if date_filter is not None:
        items = [s for s in items if s["screening_date"] == date_filter]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return paginate([serialize_screening(s) for s in items], request.args)


@bp.route("/eligibility-screenings/<screening_id>", methods=["GET"])
def get_screening(screening_id):
    get_auth(PATIENT_ROLES)
    screening = get_or_404(db.eligibility_screenings, screening_id, "eligibility screening")
    return success_object(serialize_screening(screening))


@bp.route("/eligibility-screenings", methods=["GET"])
def list_screenings_global():
    get_auth(PATIENT_ROLES)
    items = list(db.eligibility_screenings.values())
    patient_filter = request.args.get("patient_id")
    date_filter = request.args.get("screening_date")
    if patient_filter is not None:
        items = [s for s in items if s["patient_id"] == patient_filter]
    if date_filter is not None:
        items = [s for s in items if s["screening_date"] == date_filter]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    return paginate([serialize_screening(s) for s in items], request.args)
