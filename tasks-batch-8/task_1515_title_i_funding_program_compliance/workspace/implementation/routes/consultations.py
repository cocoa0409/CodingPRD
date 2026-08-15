"""EquitableServicesConsultation endpoints."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from routes.grants import get_grant_or_404
from services import serializers

bp = Blueprint("consultations", __name__)

ALL_ROLES = middleware.ROLES
OMBUDSMAN = {"PrivateSchoolOmbudsman"}


def get_consultation_or_404(consultation_id):
    c = db.consultations.get(consultation_id)
    if c is None:
        errors.fail(errors.ERR_NOT_FOUND, "Consultation %s does not exist." % consultation_id)
    return c


def _get_private_school_or_404(ps_id):
    ps = db.private_schools.get(ps_id)
    if ps is None:
        errors.fail(errors.ERR_NOT_FOUND, "Private school %s does not exist." % ps_id)
    return ps


@bp.post("/equitable-services-consultations")
def create_consultation():
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"ComplianceAnalyst"})
    data = V.json_body()
    # Tier 3: body FK existence in declared order.
    grant_ref = data.get("grant_id")
    if grant_ref is not None and isinstance(grant_ref, str):
        get_grant_or_404(grant_ref)
    ps_ref = data.get("private_school_id")
    if ps_ref is not None and isinstance(ps_ref, str):
        _get_private_school_or_404(ps_ref)
    # Tier 4: schema.
    V.check_unknown(data, {"grant_id", "private_school_id"})
    grant_id = V.req_str(data, "grant_id")
    ps_id = V.req_str(data, "private_school_id")
    grant = get_grant_or_404(grant_id)
    ps = _get_private_school_or_404(ps_id)
    # Tier 4.5: (grant, private school) pair is unique.
    for c in db.consultations.values():
        if c["grant_id"] == grant["id"] and c["private_school_id"] == ps["id"]:
            errors.fail(
                errors.ERR_DUPLICATE_CONSULTATION,
                "A consultation already exists for this grant and private school.",
            )
    # Tier 9: nonprofit verification.
    if not ps["nonprofit_verified"]:
        errors.fail(
            errors.ERR_PRIVATE_SCHOOL_NOT_VERIFIED,
            "Consultation requires nonprofit_verified == true.",
        )
    consultation = db.init_common({
        "grant_id": grant["id"],
        "private_school_id": ps["id"],
        "status": "INITIATED",
        "sessions": [],
        "agreed_low_income_count": None,
        "affirmation_signed_at": None,
        "affirmation_signer_id": None,
        "dispute_reason": None,
        "complaint_determination": None,
    })
    db.consultations[consultation["id"]] = consultation
    return response.success_object(serializers.consultation_view(consultation), 201)


@bp.get("/equitable-services-consultations")
def list_consultations():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    filters = [
        ("grant_id", V.query_filter("grant_id")),
        ("private_school_id", V.query_filter("private_school_id")),
        ("status", V.query_filter("status")),
    ]
    page, limit, offset, total = V.sorted_page(list(db.consultations.values()), filters)
    return response.success_list(
        [serializers.consultation_view(c) for c in page], limit, offset, total
    )


@bp.get("/equitable-services-consultations/<consultation_id>")
def get_consultation(consultation_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(
        serializers.consultation_view(get_consultation_or_404(consultation_id))
    )


@bp.post("/equitable-services-consultations/<consultation_id>/record-session")
def record_session(consultation_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"ComplianceAnalyst"})
    consultation = get_consultation_or_404(consultation_id)
    data = V.json_body()
    V.check_unknown(data, {"session_date", "topics", "attendee_count"})
    session_date_raw = V.req_str(data, "session_date")
    session_date = V.parse_date(session_date_raw, "session_date")
    if "topics" not in data:
        errors.fail(errors.ERR_INVALID_REQUEST, "Missing required field: topics.")
    topics = data["topics"]
    if not isinstance(topics, (str, list)):
        errors.fail(errors.ERR_INVALID_REQUEST, "Field topics must be a string or an array.")
    attendee_count = V.req_int(data, "attendee_count")
    if attendee_count < 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "attendee_count must be >= 0.")
    # Tier 5: INITIATED (first session), CONSULTING (self-loop), DISPUTED (resume).
    if consultation["status"] not in ("INITIATED", "CONSULTING", "DISPUTED"):
        errors.fail(
            errors.ERR_CONSULTATION_INVALID_STATE,
            "Sessions may only be logged from INITIATED, CONSULTING, or DISPUTED.",
        )
    # Tier 10: session date must not be after the current clock date.
    if session_date > db.clock_date():
        errors.fail(
            errors.ERR_SESSION_DATE_IN_FUTURE,
            "session_date is after the current clock date.",
        )
    consultation["sessions"].append({
        "session_date": session_date_raw,
        "topics": topics,
        "attendee_count": attendee_count,
    })
    consultation["status"] = "CONSULTING"
    db.touch(consultation)
    return response.success_object(serializers.consultation_view(consultation))


@bp.post("/equitable-services-consultations/<consultation_id>/sign-affirmation")
def sign_affirmation(consultation_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, OMBUDSMAN)
    consultation = get_consultation_or_404(consultation_id)
    data = V.json_body()
    V.check_unknown(data, {"agreed_low_income_count"})
    agreed = V.req_int(data, "agreed_low_income_count")
    if agreed < 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "agreed_low_income_count must be >= 0.")
    # Tier 5: consultation state, session floor, grant window (affirmations lock
    # before allocation).
    if consultation["status"] != "CONSULTING":
        errors.fail(
            errors.ERR_CONSULTATION_INVALID_STATE,
            "sign-affirmation requires status CONSULTING.",
        )
    if len(consultation["sessions"]) < 2:
        errors.fail(
            errors.ERR_INSUFFICIENT_CONSULTATION_SESSIONS,
            "sign-affirmation requires at least two logged sessions.",
        )
    grant = db.grants[consultation["grant_id"]]
    if grant["status"] not in ("SETUP", "RANKING_LOCKED"):
        errors.fail(
            errors.ERR_GRANT_INVALID_STATE,
            "Affirmations must be signed before the grant is ALLOCATED.",
        )
    consultation["status"] = "AFFIRMATION_SIGNED"
    consultation["agreed_low_income_count"] = agreed
    consultation["affirmation_signed_at"] = db.now_ts()
    consultation["affirmation_signer_id"] = uid
    db.touch(consultation)
    return response.success_object(serializers.consultation_view(consultation))


@bp.post("/equitable-services-consultations/<consultation_id>/dispute")
def dispute_consultation(consultation_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, OMBUDSMAN)
    consultation = get_consultation_or_404(consultation_id)
    data = V.json_body()
    V.check_unknown(data, {"dispute_reason"})
    reason = V.req_str(data, "dispute_reason")
    if consultation["status"] != "CONSULTING":
        errors.fail(
            errors.ERR_CONSULTATION_INVALID_STATE,
            "dispute requires status CONSULTING.",
        )
    consultation["status"] = "DISPUTED"
    consultation["dispute_reason"] = reason
    db.touch(consultation)
    return response.success_object(serializers.consultation_view(consultation))


@bp.post("/equitable-services-consultations/<consultation_id>/file-complaint")
def file_complaint(consultation_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, OMBUDSMAN)
    consultation = get_consultation_or_404(consultation_id)
    data = V.json_body()
    V.check_unknown(data, {"complaint_text"})
    V.req_str(data, "complaint_text")
    if consultation["status"] != "DISPUTED":
        errors.fail(
            errors.ERR_CONSULTATION_INVALID_STATE,
            "file-complaint requires status DISPUTED.",
        )
    consultation["status"] = "COMPLAINT_FILED"
    db.touch(consultation)
    return response.success_object(serializers.consultation_view(consultation))


@bp.post("/equitable-services-consultations/<consultation_id>/resolve-complaint")
def resolve_complaint(consultation_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"SEAMonitor"})
    consultation = get_consultation_or_404(consultation_id)
    data = V.json_body()
    V.check_unknown(data, {"determination_note"})
    note = V.req_str(data, "determination_note")
    if consultation["status"] != "COMPLAINT_FILED":
        errors.fail(
            errors.ERR_CONSULTATION_INVALID_STATE,
            "resolve-complaint requires status COMPLAINT_FILED.",
        )
    consultation["status"] = "CONSULTING"
    consultation["complaint_determination"] = note
    db.touch(consultation)
    return response.success_object(serializers.consultation_view(consultation))
