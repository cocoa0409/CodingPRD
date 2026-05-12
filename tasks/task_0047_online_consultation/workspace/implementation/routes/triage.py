"""TriageSession endpoints."""

from __future__ import annotations

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_REF_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_QUESTIONNAIRE_EMPTY,
)
from config import ROLE_PATIENT, ROLE_DOCTOR, ROLE_ADMIN
from services.serializers import serialize
from services.occ import check_version
from services.calculations import triage_severity_score
from services.matching import select_doctor, find_department_disease_codes
import db as _db


bp = Blueprint("triage", __name__, url_prefix="/consultation/triage-sessions")


def _ts_or_404(tid):
    row = db.find_by_id("triage_sessions", tid)
    if not row:
        raise AppError(ERR_NOT_FOUND, "TriageSession not found.", 404)
    return row


def _ensure_patient_owner(row):
    if g.role == ROLE_PATIENT and g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)


@bp.post("")
def create_triage():
    require_role(ROLE_PATIENT)
    body = request.get_json(silent=True) or {}
    patient_id = body.get("patient_id")
    if not patient_id or not db.find_by_id("patients", patient_id):
        raise AppError(ERR_REF_NOT_FOUND, "patient_id not found.", 422)
    if g.user_id != patient_id:
        raise AppError(ERR_FORBIDDEN, "Patient may only open triage for self.", 403)
    record = {
        "patient_id": patient_id,
        "questionnaire_responses": body.get("questionnaire_responses") or [],
        "chief_complaint_score": 0,
        "vital_anomaly_score": 0,
        "risk_factor_score": 0,
        "severity_score": 0,
        "severity_band": "LOW",
        "recommended_department_code": None,
        "status": "COLLECTING",
        "emergency_routing_ticket": None,
    }
    row = db.insert("triage_sessions", record)
    return success(serialize(row), 201)


def _select_department_code(disease_codes_seen):
    """Among DepartmentMappings whose disease_codes intersect, pick the one with lowest triage_priority."""
    candidates = []
    for m in db.all_rows("department_mappings"):
        if set(m.get("disease_codes") or []).intersection(disease_codes_seen):
            candidates.append(m)
    if not candidates:
        # Fall back: just pick the mapping with lowest triage_priority (or none).
        all_m = db.all_rows("department_mappings")
        if not all_m:
            return None
        candidates = all_m
    candidates.sort(key=lambda m: (m.get("triage_priority", 0), m.get("_seq", 0)))
    return candidates[0].get("department_code")


@bp.post("/<tid>/assess")
def assess(tid):
    require_role(ROLE_PATIENT)
    row = _ts_or_404(tid)
    _ensure_patient_owner(row)
    body = request.get_json(silent=True) or {}
    if row.get("status") != "COLLECTING":
        raise AppError(ERR_INVALID_STATE, "TriageSession not in COLLECTING.", 409)
    check_version(row, body)
    qs = row.get("questionnaire_responses") or []
    if len(qs) < 1:
        raise AppError(ERR_QUESTIONNAIRE_EMPTY, "Questionnaire is empty.", 422)
    patient = db.find_by_id("patients", row.get("patient_id"))
    chronic = (patient or {}).get("chronic_condition_codes") or []
    chief, vital, risk, total, band = triage_severity_score(qs, chronic)
    updates = {
        "chief_complaint_score": chief,
        "vital_anomaly_score": vital,
        "risk_factor_score": risk,
        "severity_score": total,
        "severity_band": band,
        "status": "ASSESSED",
    }
    if band != "EMERGENCY":
        # Compute recommended_department_code from disease codes seen in questionnaire
        disease_codes_seen = set()
        for r in qs:
            # Heuristic: a response that's NOT a vital can hint a disease via 'disease_code'.
            dc = r.get("disease_code")
            if dc:
                disease_codes_seen.add(dc)
        dept = _select_department_code(disease_codes_seen)
        updates["recommended_department_code"] = dept
    else:
        # Auto-transition to EMERGENCY_ROUTED
        updates["status"] = "EMERGENCY_ROUTED"
        updates["emergency_routing_ticket"] = db.new_id()
        updates["recommended_department_code"] = None
    row = db.update("triage_sessions", tid, updates)
    return success(serialize(row), 200)


@bp.post("/<tid>/close")
def close(tid):
    require_role(ROLE_PATIENT)
    row = _ts_or_404(tid)
    _ensure_patient_owner(row)
    body = request.get_json(silent=True) or {}
    if row.get("status") != "ASSESSED":
        raise AppError(ERR_INVALID_STATE, "TriageSession not in ASSESSED.", 409)
    check_version(row, body)
    row = db.update("triage_sessions", tid, {"status": "CLOSED"})
    return success(serialize(row), 200)


@bp.get("/<tid>")
def get_triage(tid):
    require_role(ROLE_PATIENT, ROLE_DOCTOR, ROLE_ADMIN)
    row = _ts_or_404(tid)
    if g.role == ROLE_PATIENT and g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)
    return success(serialize(row), 200)
