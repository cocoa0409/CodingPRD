"""University and Program routes."""
from __future__ import annotations

from flask import Blueprint, request

from core.auth import require_roles
from core.errors import raise_error
from core.response import success_object
from core.store import store
from services.engine import get_program, get_university
from services.serializers import program_out, university_out
from services.time_utils import parse_iso

bp = Blueprint("universities", __name__)


def _validate_int(value, field: str, *, minimum: int | None = None) -> int:
    if value is None:
        raise_error("ERR_VALIDATION", f"{field} is required.")
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error("ERR_VALIDATION", f"{field} must be an integer.")
    if minimum is not None and value < minimum:
        raise_error("ERR_VALIDATION", f"{field} must be >= {minimum}.")
    return value


@bp.post("/universities")
@require_roles("PlatformAdmin")
def create_university():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise_error("ERR_VALIDATION", "name is required.")
    for u in store.universities.values():
        if u["name"] == name:
            raise_error("ERR_VALIDATION", "university name must be unique.")
    target = _validate_int(body.get("yield_target_count"), "yield_target_count", minimum=1)
    rd = body.get("regular_decision_deadline")
    ed = body.get("early_decision_deadline")
    if not isinstance(rd, str):
        raise_error("ERR_VALIDATION", "regular_decision_deadline must be ISO datetime.")
    if not isinstance(ed, str):
        raise_error("ERR_VALIDATION", "early_decision_deadline must be ISO datetime.")
    try:
        parse_iso(rd)
        parse_iso(ed)
    except ValueError:
        raise_error("ERR_VALIDATION", "deadlines must be ISO datetimes.")
    rolling = body.get("rolling_admission_enabled", False)
    if rolling is None:
        rolling = False
    if not isinstance(rolling, bool):
        raise_error("ERR_VALIDATION", "rolling_admission_enabled must be a boolean.")

    rec = store.stamp_create()
    rec.update(
        {
            "name": name,
            "yield_target_count": target,
            "regular_decision_deadline": rd,
            "early_decision_deadline": ed,
            "rolling_admission_enabled": rolling,
            "enrolled_count": 0,
        }
    )
    store.universities[rec["id"]] = rec
    return success_object(university_out(rec), 201)


@bp.get("/universities/<university_id>")
@require_roles("Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin")
def read_university(university_id: str):
    rec = get_university(university_id)
    return success_object(university_out(rec), 200)


@bp.post("/universities/<university_id>/programs")
@require_roles("AdmissionsOfficer", "PlatformAdmin")
def create_program(university_id: str):
    uni = get_university(university_id)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_error("ERR_VALIDATION", "Request body must be a JSON object.")
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise_error("ERR_VALIDATION", "name is required.")
    capacity = _validate_int(body.get("capacity"), "capacity", minimum=1)
    # Name unique within university
    for p in store.programs.values():
        if p["university_id"] == uni["id"] and p["name"] == name:
            raise_error("ERR_VALIDATION", "program name must be unique within university.")
    rec = store.stamp_create()
    rec.update(
        {
            "university_id": uni["id"],
            "name": name,
            "capacity": capacity,
            "admitted_count": 0,
        }
    )
    store.programs[rec["id"]] = rec
    return success_object(program_out(rec), 201)


@bp.get("/programs/<program_id>")
@require_roles("Applicant", "AdmissionsOfficer", "FinancialAidOfficer", "PlatformAdmin")
def read_program(program_id: str):
    rec = get_program(program_id)
    return success_object(program_out(rec), 200)
