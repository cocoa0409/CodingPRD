"""Tutor + credential + subject tag routes."""

from flask import Blueprint, g, request

from config import (
    DISPLAY_NAME_MAX,
    DISPLAY_NAME_MIN,
    PROFICIENCY_LEVELS,
    TUTOR_RATE_MAX,
    TUTOR_RATE_MIN,
    CREDENTIAL_TYPES,
)
from db import db, init_common_fields, touch
from errors import APIError
from middleware import require_auth
from response import empty_response, list_response, success_response
from services.pagination import get_pagination, slice_items
from services.validators import (
    optional_enum,
    optional_int,
    optional_string,
    require_body,
    require_email,
    require_enum,
    require_field,
    require_int,
    require_string,
    require_subject_code,
)
from services.verification import recompute_tutor_verification, cascade_cancel_future_confirmed_for_tutor
from clock import parse_iso

tutor_bp = Blueprint("tutor", __name__)


def _check_version(record, supplied):
    if supplied is None:
        return
    if not isinstance(supplied, int) or isinstance(supplied, bool):
        raise APIError("ERR_VALIDATION", "Field 'version' must be an integer.")
    if supplied != record.get("version"):
        raise APIError("ERR_VERSION_CONFLICT")


@tutor_bp.route("/tutors", methods=["POST"])
@require_auth({"PlatformAdmin", "Tutor"})
def create_tutor():
    body = request.get_json(silent=True) or {}
    require_body(body)
    display_name = require_string(body, "display_name", DISPLAY_NAME_MIN, DISPLAY_NAME_MAX)
    email = require_email(body, "email")
    hourly_rate = require_int(body, "hourly_rate_cents", TUTOR_RATE_MIN, TUTOR_RATE_MAX)
    trial_rate = require_int(body, "trial_rate_cents", 0, hourly_rate)

    if email in db.tutor_emails:
        raise APIError("ERR_VALIDATION", "Email already in use.")

    tutor = init_common_fields({
        "display_name": display_name,
        "email": email,
        "hourly_rate_cents": hourly_rate,
        "trial_rate_cents": trial_rate,
        "verification_status": "UNVERIFIED",
        "subject_tags": [],
        "payout_balance_cents": 0,
        "lifetime_completed_sessions": 0,
    })
    db.tutors[tutor["id"]] = tutor
    db.tutor_emails.add(email)
    return success_response(tutor, status=201)


@tutor_bp.route("/tutors/<tutor_id>", methods=["GET"])
@require_auth({"PlatformAdmin", "Tutor", "Student", "Parent", "CredentialVerifier", "PlatformArbiter"})
def get_tutor(tutor_id):
    tutor = db.tutors.get(tutor_id)
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")
    # Tutor role: own profile only
    if g.user_role == "Tutor" and g.user_id != tutor_id:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    return success_response(tutor, status=200)


@tutor_bp.route("/tutors/<tutor_id>", methods=["PATCH"])
@require_auth({"Tutor", "PlatformAdmin"})
def patch_tutor(tutor_id):
    tutor = db.tutors.get(tutor_id)
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")
    if g.user_role == "Tutor" and g.user_id != tutor_id:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    body = request.get_json(silent=True) or {}
    require_body(body)

    version = body.get("version")
    _check_version(tutor, version)

    display_name = optional_string(body, "display_name", DISPLAY_NAME_MIN, DISPLAY_NAME_MAX)
    hourly_rate = optional_int(body, "hourly_rate_cents", TUTOR_RATE_MIN, TUTOR_RATE_MAX)
    trial_rate = optional_int(body, "trial_rate_cents", 0, None)

    if display_name is not None:
        tutor["display_name"] = display_name
    if hourly_rate is not None:
        tutor["hourly_rate_cents"] = hourly_rate
    if trial_rate is not None:
        tutor["trial_rate_cents"] = trial_rate

    # Sanity: trial_rate <= hourly_rate (after applying)
    if tutor["trial_rate_cents"] > tutor["hourly_rate_cents"]:
        raise APIError("ERR_VALIDATION", "trial_rate_cents must be <= hourly_rate_cents.")

    touch(tutor)
    return success_response(tutor, status=200)


@tutor_bp.route("/tutors", methods=["GET"])
@require_auth({"PlatformAdmin", "Student", "Parent"})
def list_tutors():
    limit, offset = get_pagination()
    subject_code = request.args.get("subject_code")
    verification_status = request.args.get("verification_status")
    max_hourly_raw = request.args.get("max_hourly_rate_cents")
    max_hourly = None
    if max_hourly_raw is not None:
        try:
            max_hourly = int(max_hourly_raw)
        except (TypeError, ValueError):
            raise APIError("ERR_VALIDATION", "max_hourly_rate_cents must be an integer.")

    items = list(db.tutors.values())
    if subject_code:
        items = [t for t in items if subject_code in t.get("subject_tags", [])]
    if verification_status:
        items = [t for t in items if t.get("verification_status") == verification_status]
    if max_hourly is not None:
        items = [t for t in items if t.get("hourly_rate_cents", 0) <= max_hourly]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = slice_items(items, limit, offset)
    return list_response(page, total, limit, offset, status=200)


@tutor_bp.route("/tutors/<tutor_id>/suspend", methods=["POST"])
@require_auth({"PlatformAdmin"})
def suspend_tutor(tutor_id):
    tutor = db.tutors.get(tutor_id)
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")
    if tutor["verification_status"] != "VERIFIED":
        raise APIError("ERR_INVALID_STATE")
    tutor["verification_status"] = "SUSPENDED"
    touch(tutor)
    cascade_cancel_future_confirmed_for_tutor(tutor["id"])
    return success_response(tutor, status=200)


@tutor_bp.route("/tutors/<tutor_id>/reinstate", methods=["POST"])
@require_auth({"PlatformAdmin"})
def reinstate_tutor(tutor_id):
    tutor = db.tutors.get(tutor_id)
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")
    if tutor["verification_status"] != "SUSPENDED":
        raise APIError("ERR_INVALID_STATE")
    # Reinstate only if posture computes VERIFIED
    from services.verification import compute_verification_posture
    # Temporarily clear so the posture rule's "previously VERIFIED -> SUSPENDED" branch
    # doesn't keep it SUSPENDED. Compute fresh.
    saved = tutor["verification_status"]
    tutor["verification_status"] = "UNVERIFIED"
    posture = compute_verification_posture(tutor)
    if posture != "VERIFIED":
        # Restore prior state and reject
        tutor["verification_status"] = saved
        raise APIError("ERR_INVALID_STATE")
    tutor["verification_status"] = "VERIFIED"
    touch(tutor)
    return success_response(tutor, status=200)


# --- Credentials ---


@tutor_bp.route("/tutors/<tutor_id>/credentials", methods=["POST"])
@require_auth({"Tutor"})
def submit_credential(tutor_id):
    tutor = db.tutors.get(tutor_id)
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")
    if g.user_id != tutor_id:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    body = request.get_json(silent=True) or {}
    require_body(body)
    credential_type = require_enum(body, "credential_type", CREDENTIAL_TYPES)
    document_ref = require_string(body, "document_ref")
    expires_at_raw = body.get("expires_at")
    expires_at = None
    if expires_at_raw is not None:
        # Validate format
        parse_iso(expires_at_raw)
        expires_at = expires_at_raw

    credential = init_common_fields({
        "tutor_id": tutor_id,
        "credential_type": credential_type,
        "document_ref": document_ref,
        "status": "SUBMITTED",
        "reviewed_by": None,
        "expires_at": expires_at,
    })
    db.credentials[credential["id"]] = credential

    # Tutor UNVERIFIED -> PENDING_REVIEW
    if tutor["verification_status"] == "UNVERIFIED":
        tutor["verification_status"] = "PENDING_REVIEW"
        touch(tutor)

    return success_response(credential, status=201)


def _get_credential(tutor_id, credential_id):
    tutor = db.tutors.get(tutor_id)
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")
    cred = db.credentials.get(credential_id)
    if cred is None or cred["tutor_id"] != tutor_id:
        raise APIError("ERR_NOT_FOUND")
    return tutor, cred


@tutor_bp.route("/tutors/<tutor_id>/credentials/<credential_id>/approve", methods=["POST"])
@require_auth({"CredentialVerifier"})
def approve_credential(tutor_id, credential_id):
    tutor, cred = _get_credential(tutor_id, credential_id)
    if cred["status"] != "SUBMITTED":
        raise APIError("ERR_INVALID_STATE")
    if g.user_id == tutor_id:
        raise APIError("ERR_SEGREGATION_VIOLATION")
    cred["status"] = "APPROVED"
    cred["reviewed_by"] = g.user_id
    touch(cred)
    recompute_tutor_verification(tutor)
    return success_response(cred, status=200)


@tutor_bp.route("/tutors/<tutor_id>/credentials/<credential_id>/reject", methods=["POST"])
@require_auth({"CredentialVerifier"})
def reject_credential(tutor_id, credential_id):
    tutor, cred = _get_credential(tutor_id, credential_id)
    if cred["status"] != "SUBMITTED":
        raise APIError("ERR_INVALID_STATE")
    if g.user_id == tutor_id:
        raise APIError("ERR_SEGREGATION_VIOLATION")
    cred["status"] = "REJECTED"
    cred["reviewed_by"] = g.user_id
    touch(cred)
    recompute_tutor_verification(tutor)
    return success_response(cred, status=200)


# --- Subject tags ---


@tutor_bp.route("/tutors/<tutor_id>/subjects", methods=["POST"])
@require_auth({"Tutor"})
def propose_subject(tutor_id):
    tutor = db.tutors.get(tutor_id)
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")
    if g.user_id != tutor_id:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    body = request.get_json(silent=True) or {}
    require_body(body)
    subject_code = require_subject_code(body, "subject_code")
    proficiency = require_enum(body, "proficiency_level", PROFICIENCY_LEVELS)

    # Uniqueness on (tutor_id, subject_code) over non-REMOVED tags
    for st in db.subject_tags.values():
        if st["tutor_id"] == tutor_id and st["subject_code"] == subject_code and st["status"] != "REMOVED":
            raise APIError("ERR_VALIDATION", "Subject already proposed for this tutor.")

    tag = init_common_fields({
        "tutor_id": tutor_id,
        "subject_code": subject_code,
        "proficiency_level": proficiency,
        "status": "PROPOSED",
    })
    db.subject_tags[tag["id"]] = tag
    return success_response(tag, status=201)


def _get_subject(tutor_id, subject_id):
    tutor = db.tutors.get(tutor_id)
    if tutor is None:
        raise APIError("ERR_NOT_FOUND")
    tag = db.subject_tags.get(subject_id)
    if tag is None or tag["tutor_id"] != tutor_id:
        raise APIError("ERR_NOT_FOUND")
    return tutor, tag


@tutor_bp.route("/tutors/<tutor_id>/subjects/<subject_id>/approve", methods=["POST"])
@require_auth({"CredentialVerifier"})
def approve_subject(tutor_id, subject_id):
    tutor, tag = _get_subject(tutor_id, subject_id)
    if tag["status"] != "PROPOSED":
        raise APIError("ERR_INVALID_STATE")
    if g.user_id == tutor_id:
        raise APIError("ERR_SEGREGATION_VIOLATION")
    if tutor["verification_status"] != "VERIFIED":
        raise APIError("ERR_TUTOR_NOT_VERIFIED")
    tag["status"] = "APPROVED"
    touch(tag)
    # Append to tutor cache
    if tag["subject_code"] not in tutor["subject_tags"]:
        tutor["subject_tags"].append(tag["subject_code"])
        touch(tutor)
    return success_response(tag, status=200)


@tutor_bp.route("/tutors/<tutor_id>/subjects/<subject_id>", methods=["DELETE"])
@require_auth({"Tutor", "PlatformAdmin"})
def delete_subject(tutor_id, subject_id):
    tutor, tag = _get_subject(tutor_id, subject_id)
    if g.user_role == "Tutor" and g.user_id != tutor_id:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    if tag["status"] == "REMOVED":
        raise APIError("ERR_INVALID_STATE")
    if tag["status"] == "APPROVED":
        # Cannot remove if active sessions exist for this (tutor_id, subject_code)
        for s in db.sessions.values():
            if (
                s["tutor_id"] == tutor_id
                and s["subject_code"] == tag["subject_code"]
                and s["status"] in ("REQUESTED", "CONFIRMED", "IN_PROGRESS")
            ):
                raise APIError("ERR_INVALID_STATE")
        # Remove from cache
        if tag["subject_code"] in tutor["subject_tags"]:
            tutor["subject_tags"].remove(tag["subject_code"])
            touch(tutor)
    tag["status"] = "REMOVED"
    touch(tag)
    return empty_response(status=204)
