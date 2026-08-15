"""WorkerInterviewRecord endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
    ERR_AUDIT_INVALID_STATE,
    ERR_RECORD_ALREADY_EXISTS,
    ERR_INTERVIEW_SAMPLE_TOO_SMALL,
)
from services.utils import new_uuid, ceil_sqrt

bp = Blueprint("interviews", __name__)


def serialize(r):
    out = {
        "id": r["id"],
        "audit_id": r["audit_id"],
        "interview_count": r["interview_count"],
        "forced_labor_indicators": r["forced_labor_indicators"],
        "recruitment_fee_indicators": r["recruitment_fee_indicators"],
        "notes": r.get("notes"),
        "created_at": r["created_at"],
    }
    return out


@bp.route("/audits/<audit_id>/worker-interviews", methods=["POST"])
def create_interview_record(audit_id):
    user_id, _ = require_roles("Auditor")
    body = request.get_json(silent=True) or {}
    interview_count = body.get("interview_count")
    fl = body.get("forced_labor_indicators")
    rf = body.get("recruitment_fee_indicators")
    notes = body.get("notes")
    if not isinstance(interview_count, int) or isinstance(interview_count, bool) or interview_count < 0:
        raise_err(ERR_INVALID_REQUEST, "interview_count must be a non-negative integer")
    if not isinstance(fl, bool):
        raise_err(ERR_INVALID_REQUEST, "forced_labor_indicators must be a boolean")
    if not isinstance(rf, bool):
        raise_err(ERR_INVALID_REQUEST, "recruitment_fee_indicators must be a boolean")
    audit = db.audits.get(audit_id)
    if not audit:
        raise_err(ERR_NOT_FOUND, "audit not found")
    # State: must be IN_PROGRESS (the audit status that permits recording interviews)
    if audit["status"] != "IN_PROGRESS":
        raise_err(ERR_AUDIT_INVALID_STATE, f"audit status is {audit['status']}")
    if user_id != audit["auditor_id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller is not the audit's lead auditor")
    # One per audit
    existing = next((r for r in db.worker_interview_records.values() if r["audit_id"] == audit_id), None)
    if existing is not None:
        raise_err(ERR_RECORD_ALREADY_EXISTS, "worker interview record already exists for this audit")
    # Sample size check
    facility = db.facilities.get(audit["facility_id"])
    if facility is None:
        raise_err(ERR_NOT_FOUND, "facility not found")
    min_sample = ceil_sqrt(facility["worker_count"])
    if interview_count < min_sample:
        raise_err(ERR_INTERVIEW_SAMPLE_TOO_SMALL,
                  f"interview_count {interview_count} < minimum {min_sample}")
    rec = {
        "id": new_uuid(),
        "audit_id": audit_id,
        "interview_count": interview_count,
        "forced_labor_indicators": fl,
        "recruitment_fee_indicators": rf,
        "notes": notes if isinstance(notes, str) else None,
        "created_at": db.get_clock(),
    }
    db.worker_interview_records[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.route("/audits/<audit_id>/worker-interviews", methods=["GET"])
def list_interview_records(audit_id):
    require_roles(*ALL_BUSINESS_ROLES)
    audit = db.audits.get(audit_id)
    if not audit:
        raise_err(ERR_NOT_FOUND, "audit not found")
    limit, offset = get_pagination()
    items = [r for r in db.worker_interview_records.values() if r["audit_id"] == audit_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize(r) for r in page], total, limit, offset)
