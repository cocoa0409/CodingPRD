"""Candidate + EEORecord routes."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import iso_format, now
from ..common import bump, get_json_body, require_enum, require_fields, require_str, stamp_new
from ..errors import ApiError
from ..lookups import path_candidate, employee_exists
from ..response import respond
from ..serializers import serialize_candidate, serialize_eeo_record
from ..store import store


candidates_bp = Blueprint("candidates", __name__)


CANDIDATE_SOURCES = {"DIRECT", "AGENCY", "REFERRAL", "EVENT", "INBOUND"}
EEO_GENDER = {"MALE", "FEMALE", "NON_BINARY", "DECLINE"}
EEO_ETHNICITY = {
    "HISPANIC_LATINO", "WHITE", "BLACK_AFRICAN_AMERICAN", "NATIVE_HAWAIIAN_PI",
    "ASIAN", "AMERICAN_INDIAN_AN", "TWO_OR_MORE", "DECLINE",
}
EEO_VETERAN = {"NOT_VETERAN", "PROTECTED_VETERAN", "OTHER_VETERAN", "DECLINE"}
EEO_DISABILITY = {"YES", "NO", "DECLINE"}


@candidates_bp.post("/candidates")
@require_auth("Recruiter", "PlatformAdmin")
def create_candidate():
    body = get_json_body()
    require_fields(body, "email", "full_name", "source")
    email = require_str(body["email"], "email")
    full_name = require_str(body["full_name"], "full_name")
    source = require_enum(body["source"], "source", CANDIDATE_SOURCES)
    referrer_employee_id = body.get("referrer_employee_id")
    is_protected = body.get("is_in_eeo_protected_class", False)
    if not isinstance(is_protected, bool):
        raise ApiError("ERR_VALIDATION", "is_in_eeo_protected_class must be a boolean")

    # Referral consistency check (priority 9).
    if source == "REFERRAL":
        if referrer_employee_id is None:
            raise ApiError(
                "ERR_REFERRAL_REQUIRES_REFERRER",
                "Candidate.source == REFERRAL requires a non-null referrer_employee_id",
            )
    else:
        if referrer_employee_id is not None:
            raise ApiError(
                "ERR_REFERRAL_REQUIRES_REFERRER",
                "Candidate.source != REFERRAL requires referrer_employee_id to be null",
            )

    with store.lock:
        # Uniqueness on email.
        for c in store.candidates.values():
            if c["email"] == email:
                raise ApiError("ERR_VALIDATION", "candidate email is already in use")

        # Referrer must exist (priority 4: foreign-key existence -> ERR_REFERENCE_NOT_FOUND).
        if referrer_employee_id is not None and not employee_exists(referrer_employee_id):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "referrer_employee_id does not match any employee")

        candidate = stamp_new({
            "email": email,
            "full_name": full_name,
            "source": source,
            "referrer_employee_id": referrer_employee_id,
            "is_in_eeo_protected_class": is_protected,
        })
        store.candidates[candidate["id"]] = candidate
    return respond(serialize_candidate(candidate), 201)


@candidates_bp.get("/candidates/<cid>")
@require_auth("Recruiter", "HiringManager", "PlatformAdmin")
def get_candidate(cid):
    with store.lock:
        return respond(serialize_candidate(path_candidate(cid)))


@candidates_bp.post("/candidates/<cid>/eeo-record")
@require_auth("Candidate", "ComplianceOfficer")
def attach_eeo_record(cid):
    body = get_json_body()
    require_fields(body, "gender", "ethnicity", "veteran_status", "disability_status")
    gender = require_enum(body["gender"], "gender", EEO_GENDER)
    ethnicity = require_enum(body["ethnicity"], "ethnicity", EEO_ETHNICITY)
    veteran = require_enum(body["veteran_status"], "veteran_status", EEO_VETERAN)
    disability = require_enum(body["disability_status"], "disability_status", EEO_DISABILITY)

    with store.lock:
        candidate = path_candidate(cid)
        # Ownership: if acting as Candidate, must match candidate id.
        if g.user_role == "Candidate" and g.user_id != candidate["id"]:
            raise ApiError("ERR_FORBIDDEN", "Candidate may only attach own EEORecord")
        if candidate["id"] in store.eeo_by_candidate:
            raise ApiError("ERR_INVALID_STATE", "EEORecord already exists for this candidate")
        ts = iso_format(now())
        eeo = stamp_new(
            {
                "candidate_id": candidate["id"],
                "gender": gender,
                "ethnicity": ethnicity,
                "veteran_status": veteran,
                "disability_status": disability,
                "submitted_at": ts,
            },
            with_common=False,
        )
        store.eeo_records[eeo["id"]] = eeo
        store.eeo_by_candidate[candidate["id"]] = eeo["id"]
        # Bump candidate so the version moves (pinned snapshot will diverge from current).
        bump(candidate)
    return respond(serialize_eeo_record(eeo), 201)


@candidates_bp.get("/candidates/<cid>/eeo-record")
@require_auth("Candidate", "ComplianceOfficer")
def get_eeo_record(cid):
    with store.lock:
        candidate = path_candidate(cid)
        if g.user_role == "Candidate" and g.user_id != candidate["id"]:
            raise ApiError("ERR_FORBIDDEN", "Candidate may only read own EEORecord")
        eeo_id = store.eeo_by_candidate.get(candidate["id"])
        if eeo_id is None:
            raise ApiError("ERR_NOT_FOUND", "EEORecord not found")
        return respond(serialize_eeo_record(store.eeo_records[eeo_id]))
