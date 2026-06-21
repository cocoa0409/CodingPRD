"""Patient + ToothChartEntry endpoints (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_PATIENT_INACTIVE,
    ERR_PATIENT_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import (
    ROLE_BILLING,
    ROLE_CLINICIAN,
    ROLE_FRONT_DESK,
    ROLE_PATIENT,
    current_role,
    current_user_id,
)
from response import ok_array, ok_object
from routes._helpers import apply_filters, enforce_patient_ownership, guard
from services import common

bp = Blueprint("patients", __name__)

SURFACES = {"M", "O", "D", "B", "L", "I"}


@bp.post("/patients")
def create_patient():
    guard([ROLE_FRONT_DESK])
    body = common.get_json_body()
    common.require_fields(body, ["full_name", "date_of_birth"])
    full_name = common.require_string(body, "full_name")
    dob = common.require_string(body, "date_of_birth")
    rec = common.new_common_fields()
    rec.update({
        "full_name": full_name,
        "date_of_birth": dob,
        "status": "ACTIVE",
        "balance_owed_cents": 0,
    })
    db.patients[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/patients")
def list_patients():
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING])
    records = list(db.patients.values())
    records = apply_filters(records, {"status": request.args.get("status")})
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/patients/<patient_id>")
def get_patient(patient_id):
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING, ROLE_PATIENT])
    rec = common.resolve(db.patients, patient_id, ERR_PATIENT_NOT_FOUND)
    enforce_patient_ownership(rec["id"])
    return ok_object(common.serialize(rec), 200)


@bp.post("/patients/<patient_id>/deactivate")
def deactivate_patient(patient_id):
    guard([ROLE_FRONT_DESK])
    rec = common.resolve(db.patients, patient_id, ERR_PATIENT_NOT_FOUND)
    rec["status"] = "INACTIVE"
    common.touch(rec)
    return ok_object(common.serialize(rec), 200)


@bp.post("/patients/<patient_id>/tooth-chart")
def create_tooth_chart(patient_id):
    guard([ROLE_CLINICIAN])
    patient = common.resolve(db.patients, patient_id, ERR_PATIENT_NOT_FOUND)
    body = common.get_json_body()
    # body FK + required-field validation (existence of provider before body shape
    # per §2.8: path resolved above, then body FKs, then body well-formedness)
    common.require_fields(body, ["provider_id", "tooth_number", "chart_type", "finding"])
    provider_id = common.require_string(body, "provider_id")
    common.resolve(db.providers, provider_id, ERR_PROVIDER_NOT_FOUND)

    tooth_number = common.require_int(body, "tooth_number")
    if not (1 <= tooth_number <= 32):
        raise APIError(ERR_VALIDATION, 422, "tooth_number must be in 1..32")
    chart_type = common.require_enum(body, "chart_type", {"SURFACE", "PERIO"})
    finding = common.require_string(body, "finding")

    surface = None
    pocket_depth_mm = None
    if chart_type == "SURFACE":
        if body.get("surface") is None:
            raise APIError(ERR_VALIDATION, 422, "surface required for SURFACE chart_type")
        surface = common.require_enum(body, "surface", SURFACES)
    else:  # PERIO
        if body.get("pocket_depth_mm") is None:
            raise APIError(ERR_VALIDATION, 422, "pocket_depth_mm required for PERIO chart_type")
        pocket_depth_mm = common.require_int(body, "pocket_depth_mm")
        if not (1 <= pocket_depth_mm <= 12):
            raise APIError(ERR_VALIDATION, 422, "pocket_depth_mm must be in 1..12")

    # Charting on an inactive patient is rejected (PRD §3.1).
    if patient["status"] != "ACTIVE":
        raise APIError(ERR_PATIENT_INACTIVE, 409, "Patient is INACTIVE")

    rec = common.new_common_fields()
    rec.update({
        "patient_id": patient["id"],
        "provider_id": provider_id,
        "tooth_number": tooth_number,
        "chart_type": chart_type,
        "surface": surface,
        "pocket_depth_mm": pocket_depth_mm,
        "finding": finding,
    })
    db.tooth_chart_entries[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/tooth-chart-entries")
def list_tooth_chart_entries():
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING, ROLE_PATIENT])
    records = list(db.tooth_chart_entries.values())
    records = apply_filters(records, {
        "patient_id": request.args.get("patient_id"),
        "provider_id": request.args.get("provider_id"),
        "chart_type": request.args.get("chart_type"),
    })
    # Patient role: restrict to own entries (PRD §2.1).
    if current_role() == ROLE_PATIENT:
        records = [r for r in records if r["patient_id"] == current_user_id()]
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/tooth-chart-entries/<entry_id>")
def get_tooth_chart_entry(entry_id):
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING, ROLE_PATIENT])
    # No dedicated not-found code for ToothChartEntry exists in the PRD §5 catalog;
    # a missing entry returns a 404 with a descriptive id.
    rec = common.resolve(db.tooth_chart_entries, entry_id, "ERR_TOOTH_CHART_ENTRY_NOT_FOUND")
    enforce_patient_ownership(rec["patient_id"])
    return ok_object(common.serialize(rec), 200)
