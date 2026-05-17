"""AllergyRecord routes. Allergies are immutable once created."""
from __future__ import annotations

from flask import Blueprint, jsonify

from .. import store
from ..auth import require_roles
from ..clock import format_iso, now
from ..errors import APIError
from ..helpers import (
    ensure_enum,
    paginate,
    parse_json_body,
    parse_pagination,
    require_field,
)
from ..responses import build_envelope


bp = Blueprint("allergies", __name__)


ALLERGEN_VALUES = {"EGG", "LATEX", "NEOMYCIN", "GELATIN", "YEAST", "OTHER"}
SEVERITY_VALUES = {"MILD", "MODERATE", "SEVERE", "ANAPHYLAXIS"}


def _serialize(a: dict) -> dict:
    # AllergyRecord has NO updated_at / version (immutable).
    return {
        "id": a["id"],
        "patient_id": a["patient_id"],
        "allergen_code": a["allergen_code"],
        "severity": a["severity"],
        "recorded_at": a["recorded_at"],
        "created_at": a["created_at"],
    }


@bp.post("/patients/<patient_id>/allergies")
@require_roles(["ProviderClinician"])
def create_allergy(patient_id: str):
    if patient_id not in store.patients:
        raise APIError("ERR_PATIENT_NOT_FOUND", f"Patient {patient_id} not found.")
    body = parse_json_body()
    allergen = ensure_enum(require_field(body, "allergen_code"), ALLERGEN_VALUES, "allergen_code")
    severity = ensure_enum(require_field(body, "severity"), SEVERITY_VALUES, "severity")
    with store.lock:
        ts = format_iso(now())
        rec = {
            "patient_id": patient_id,
            "allergen_code": allergen,
            "severity": severity,
            "recorded_at": ts,
        }
        # Immutable record: only id + created_at are stamped (no updated_at, no version).
        store.stamp_create(rec, include_version=False)
        store.allergy_records[rec["id"]] = rec
    return jsonify(build_envelope(_serialize(rec), "object")), 201


@bp.get("/patients/<patient_id>/allergies")
@require_roles(["ProviderClinician", "ReviewingClinician", "PublicHealthOfficer"])
def list_allergies(patient_id: str):
    if patient_id not in store.patients:
        raise APIError("ERR_PATIENT_NOT_FOUND", f"Patient {patient_id} not found.")
    limit, offset = parse_pagination()
    rows = [a for a in store.allergy_records.values() if a.get("patient_id") == patient_id]
    rows.sort(key=lambda r: r["created_at"])
    page, meta = paginate(rows, limit, offset)
    return jsonify(build_envelope([_serialize(r) for r in page], "array", meta)), 200
