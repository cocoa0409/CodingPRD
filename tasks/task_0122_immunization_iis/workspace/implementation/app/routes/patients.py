"""Patient routes: registration, single read, list, next-due projection."""
from __future__ import annotations

from datetime import date
from typing import Any

from flask import Blueprint, jsonify, request

from .. import store
from ..auth import require_roles
from ..clock import now
from ..errors import APIError
from ..helpers import (
    ensure_enum,
    is_bool,
    is_nonempty_string,
    optional_field,
    paginate,
    parse_iso_date_or_400,
    parse_json_body,
    parse_pagination,
    require_field,
)
from ..responses import build_envelope
from ..services.calculations import project_next_due


bp = Blueprint("patients", __name__)


SEX_VALUES = {"FEMALE", "MALE", "UNKNOWN"}
PATIENT_STATUSES = {"ACTIVE", "DECEASED", "MERGED_OUT", "ARCHIVED"}


def _validate_name(value: Any, field: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value) <= 80):
        raise APIError("ERR_VALIDATION", f"{field} must be a string of 1..80 chars.")
    return value


def _serialize_patient(p: dict) -> dict:
    return {
        "id": p["id"],
        "first_name": p["first_name"],
        "last_name": p["last_name"],
        "date_of_birth": p["date_of_birth"],
        "sex_at_birth": p["sex_at_birth"],
        "state_resident": p["state_resident"],
        "guardian_contact_email": p["guardian_contact_email"],
        "medical_exemption_on_file": p["medical_exemption_on_file"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# -----------------------------------------------------------------------------
# POST /patients
# -----------------------------------------------------------------------------
@bp.post("/patients")
@require_roles(["SchoolRegistrar", "ProviderClinician", "PublicHealthOfficer"])
def create_patient():
    body = parse_json_body()
    first_name = _validate_name(require_field(body, "first_name"), "first_name")
    last_name = _validate_name(require_field(body, "last_name"), "last_name")
    dob_raw = require_field(body, "date_of_birth")
    dob = parse_iso_date_or_400(dob_raw, "date_of_birth")
    # Must be strictly in the past relative to server's current time.
    current_date = now().date()
    if dob >= current_date:
        raise APIError("ERR_VALIDATION", "date_of_birth must be strictly in the past.")
    sex = ensure_enum(require_field(body, "sex_at_birth"), SEX_VALUES, "sex_at_birth")

    state_resident = optional_field(body, "state_resident", default=True, type_check=is_bool)
    guardian_email = optional_field(body, "guardian_contact_email", default=None)
    if state_resident and (not isinstance(guardian_email, str) or not guardian_email):
        raise APIError("ERR_VALIDATION", "guardian_contact_email is required for state residents.")
    if guardian_email is not None and not isinstance(guardian_email, str):
        raise APIError("ERR_VALIDATION", "guardian_contact_email must be a string.")

    medical_exemption = optional_field(body, "medical_exemption_on_file", default=False, type_check=is_bool)

    with store.lock:
        record = {
            "first_name": first_name,
            "last_name": last_name,
            "date_of_birth": dob.isoformat(),
            "sex_at_birth": sex,
            "state_resident": bool(state_resident),
            "guardian_contact_email": guardian_email,
            "medical_exemption_on_file": bool(medical_exemption),
            "status": "ACTIVE",
        }
        store.stamp_create(record)
        store.patients[record["id"]] = record

    return jsonify(build_envelope(_serialize_patient(record), "object")), 201


# -----------------------------------------------------------------------------
# GET /patients/{patient_id}
# -----------------------------------------------------------------------------
@bp.get("/patients/<patient_id>")
@require_roles(["SchoolRegistrar", "ProviderClinician", "ReviewingClinician", "PublicHealthOfficer"])
def read_patient(patient_id: str):
    p = store.patients.get(patient_id)
    if not p:
        raise APIError("ERR_PATIENT_NOT_FOUND", f"Patient {patient_id} not found.")
    return jsonify(build_envelope(_serialize_patient(p), "object")), 200


# -----------------------------------------------------------------------------
# GET /patients
# -----------------------------------------------------------------------------
@bp.get("/patients")
@require_roles(["PublicHealthOfficer"])
def list_patients():
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    state_resident_filter = request.args.get("state_resident")
    dob_after = request.args.get("date_of_birth_after")
    dob_before = request.args.get("date_of_birth_before")

    if status_filter is not None and status_filter not in PATIENT_STATUSES:
        raise APIError("ERR_VALIDATION", "status filter has invalid value.")
    state_bool = None
    if state_resident_filter is not None:
        if state_resident_filter.lower() in ("true", "1"):
            state_bool = True
        elif state_resident_filter.lower() in ("false", "0"):
            state_bool = False
        else:
            raise APIError("ERR_VALIDATION", "state_resident filter must be boolean.")
    dob_after_d = parse_iso_date_or_400(dob_after, "date_of_birth_after") if dob_after else None
    dob_before_d = parse_iso_date_or_400(dob_before, "date_of_birth_before") if dob_before else None

    rows = list(store.patients.values())
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if state_bool is not None:
        rows = [r for r in rows if r["state_resident"] is state_bool]
    if dob_after_d is not None:
        rows = [r for r in rows if date.fromisoformat(r["date_of_birth"]) > dob_after_d]
    if dob_before_d is not None:
        rows = [r for r in rows if date.fromisoformat(r["date_of_birth"]) < dob_before_d]

    rows.sort(key=lambda r: r["created_at"])
    page, meta = paginate(rows, limit, offset)
    return jsonify(build_envelope([_serialize_patient(r) for r in page], "array", meta)), 200


# -----------------------------------------------------------------------------
# GET /patients/{patient_id}/next-due
# -----------------------------------------------------------------------------
@bp.get("/patients/<patient_id>/next-due")
@require_roles(["ProviderClinician", "SchoolRegistrar"])
def next_due(patient_id: str):
    p = store.patients.get(patient_id)
    if not p:
        raise APIError("ERR_PATIENT_NOT_FOUND", f"Patient {patient_id} not found.")

    # Determine the set of antigens for which there are schedule rules.
    antigens = sorted({r["antigen"] for r in store.antigen_schedule_rules.values()})
    out = []
    for antigen in antigens:
        projection = project_next_due(p, antigen)
        if projection is None:
            continue
        out.append(projection)

    return jsonify(build_envelope(out, "array")), 200
