"""SchoolEnrollmentCertificate routes."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from .. import store
from ..auth import require_roles
from ..clock import format_iso, now
from ..errors import APIError
from ..helpers import (
    check_version_conflict,
    ensure_enum,
    paginate,
    parse_json_body,
    parse_pagination,
    require_field,
    validate_school_year,
)
from ..responses import build_envelope
from ..services.calculations import evaluate_school_coverage


bp = Blueprint("certificates", __name__)


GRADE_VALUES = {"K"} | {f"G{i}" for i in range(1, 13)}
CERT_STATUSES = {"DRAFT", "ISSUED", "DEFICIENT", "EXEMPTION_GRANTED", "REVOKED"}


def _serialize(c: dict) -> dict:
    return {
        "id": c["id"],
        "patient_id": c["patient_id"],
        "school_year": c["school_year"],
        "grade_level": c["grade_level"],
        "certificate_status": c["certificate_status"],
        "missing_antigens": c["missing_antigens"],
        "issued_at": c.get("issued_at"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _require_patient(patient_id: str) -> dict:
    p = store.patients.get(patient_id)
    if not p:
        raise APIError("ERR_PATIENT_NOT_FOUND", f"Patient {patient_id} not found.")
    return p


def _require_cert(patient_id: str, cert_id: str) -> dict:
    _require_patient(patient_id)
    c = store.school_certificates.get(cert_id)
    if not c or c.get("patient_id") != patient_id:
        raise APIError("ERR_CERTIFICATE_NOT_FOUND", f"Certificate {cert_id} not found under patient.")
    return c


@bp.post("/patients/<patient_id>/certificates")
@require_roles(["SchoolRegistrar"])
def create_certificate(patient_id: str):
    body = parse_json_body()
    _require_patient(patient_id)
    school_year = validate_school_year(require_field(body, "school_year"))
    grade = ensure_enum(require_field(body, "grade_level"), GRADE_VALUES, "grade_level")
    # Uniqueness: at most one non-REVOKED certificate per (patient_id, school_year).
    for existing in store.school_certificates.values():
        if (
            existing["patient_id"] == patient_id
            and existing["school_year"] == school_year
            and existing["certificate_status"] != "REVOKED"
        ):
            raise APIError("ERR_CERTIFICATE_DUPLICATE",
                           "A non-REVOKED certificate already exists for this patient and school_year.")
    with store.lock:
        rec = {
            "patient_id": patient_id,
            "school_year": school_year,
            "grade_level": grade,
            "certificate_status": "DRAFT",
            "missing_antigens": [],
            "issued_at": None,
        }
        store.stamp_create(rec)
        store.school_certificates[rec["id"]] = rec
    return jsonify(build_envelope(_serialize(rec), "object")), 201


@bp.post("/patients/<patient_id>/certificates/<cert_id>/issue")
@require_roles(["SchoolRegistrar"])
def issue_certificate(patient_id: str, cert_id: str):
    body = parse_json_body(required=False)
    patient = _require_patient(patient_id)
    cert = _require_cert(patient_id, cert_id)
    if cert["certificate_status"] != "DRAFT":
        raise APIError("ERR_INVALID_STATE", f"Certificate is in state {cert['certificate_status']}.")
    check_version_conflict(body, cert)
    with store.lock:
        new_status, missing = evaluate_school_coverage(patient)
        cert["certificate_status"] = new_status
        cert["missing_antigens"] = missing
        if new_status in {"ISSUED", "EXEMPTION_GRANTED"}:
            cert["issued_at"] = format_iso(now())
        store.stamp_update(cert)
    return jsonify(build_envelope(_serialize(cert), "object")), 200


@bp.post("/patients/<patient_id>/certificates/<cert_id>/revoke")
@require_roles(["SchoolRegistrar"])
def revoke_certificate(patient_id: str, cert_id: str):
    body = parse_json_body(required=False)
    cert = _require_cert(patient_id, cert_id)
    if cert["certificate_status"] not in {"ISSUED", "DEFICIENT", "EXEMPTION_GRANTED"}:
        raise APIError("ERR_INVALID_STATE", f"Certificate is in state {cert['certificate_status']}.")
    check_version_conflict(body, cert)
    with store.lock:
        cert["certificate_status"] = "REVOKED"
        store.stamp_update(cert)
    return jsonify(build_envelope(_serialize(cert), "object")), 200


@bp.get("/patients/<patient_id>/certificates")
@require_roles(["SchoolRegistrar", "ProviderClinician", "PublicHealthOfficer"])
def list_certificates(patient_id: str):
    _require_patient(patient_id)
    limit, offset = parse_pagination()
    school_year = request.args.get("school_year")
    status = request.args.get("certificate_status")
    if school_year is not None:
        validate_school_year(school_year)
    if status is not None and status not in CERT_STATUSES:
        raise APIError("ERR_VALIDATION", "certificate_status filter invalid.")
    rows = [c for c in store.school_certificates.values() if c.get("patient_id") == patient_id]
    if school_year is not None:
        rows = [r for r in rows if r["school_year"] == school_year]
    if status is not None:
        rows = [r for r in rows if r["certificate_status"] == status]
    rows.sort(key=lambda r: r["created_at"])
    page, meta = paginate(rows, limit, offset)
    return jsonify(build_envelope([_serialize(r) for r in page], "array", meta)), 200
