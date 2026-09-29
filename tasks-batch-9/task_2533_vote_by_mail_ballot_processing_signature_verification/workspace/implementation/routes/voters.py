"""Voter registration records and the permanent absentee list."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import (
    CONFIRMATION_EVIDENCE_TYPES,
    PARTY_AFFILIATIONS,
    REGISTRATION_STATUSES,
    UOCAVA_STATUSES,
)
from errors import ApiError
from services import logbook

bp = Blueprint("voters", __name__)

VOTER_READ_ROLES = ("ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor")


@bp.post("/voters")
def create_voter():
    mw.require_roles("ElectionsClerk", "ElectionsAdmin")
    payload = mw.body()
    full_name = mw.require_string(payload, "full_name")
    party_affiliation = mw.require_enum(payload, "party_affiliation", PARTY_AFFILIATIONS)
    residence_address = mw.require_string(payload, "residence_address")
    last_signature_update_at = mw.require_datetime(payload, "last_signature_update_at")
    registration_status = mw.optional_enum(
        payload, "registration_status", REGISTRATION_STATUSES, "ACTIVE"
    )
    mailing_address = mw.optional_string(payload, "mailing_address", None)
    uocava_status = mw.optional_enum(payload, "uocava_status", UOCAVA_STATUSES, "NONE")
    signature_on_file_count = mw.optional_int(
        payload, "signature_on_file_count", 1, minimum=1
    )

    rec = db.make_record(
        db.voters,
        {
            "full_name": full_name,
            "party_affiliation": party_affiliation,
            "registration_status": registration_status,
            "residence_address": residence_address,
            "mailing_address": mailing_address,
            "uocava_status": uocava_status,
            "signature_on_file_count": signature_on_file_count,
            "last_signature_update_at": last_signature_update_at,
            "permanent_absentee_active": False,
            "provisional_ballot_eligible": False,
        },
    )
    return response.record_response(rec, 201)


@bp.get("/voters/<voter_id>")
def get_voter(voter_id):
    mw.require_roles(*VOTER_READ_ROLES)
    return response.record_response(lookups.voter(voter_id))


@bp.get("/voters")
def list_voters():
    mw.require_roles(*VOTER_READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.voters.values()), ["registration_status", "uocava_status"]
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/voters/<voter_id>/permanent-absentee-enrollments")
def create_enrollment(voter_id):
    mw.require_roles("ElectionsClerk")
    mw.body()
    voter_rec = lookups.voter(voter_id)
    rec = db.make_record(
        db.enrollments,
        {
            "voter_id": voter_rec["id"],
            "status": "ACTIVE",
            "consecutive_undeliverable_count": 0,
            "last_confirmation_at": db.now(),
            "suspension_reason_code": None,
            "reinstated_count": 0,
        },
    )
    voter_rec["permanent_absentee_active"] = True
    db.touch(voter_rec)
    return response.record_response(rec, 201)


@bp.get("/permanent-absentee-enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    mw.require_roles(*VOTER_READ_ROLES)
    return response.record_response(lookups.enrollment(enrollment_id))


@bp.get("/permanent-absentee-enrollments")
def list_enrollments():
    mw.require_roles(*VOTER_READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(list(db.enrollments.values()), ["voter_id", "status"])
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/permanent-absentee-enrollments/<enrollment_id>/reinstate")
def reinstate_enrollment(enrollment_id):
    actor = mw.require_roles("ElectionsClerk")
    payload = mw.body()
    confirmation_evidence_type = mw.require_enum(
        payload, "confirmation_evidence_type", CONFIRMATION_EVIDENCE_TYPES
    )
    rec = lookups.enrollment(enrollment_id)
    if rec["status"] != "SUSPENDED":
        raise ApiError("ERR_ENROLLMENT_NOT_SUSPENDED")

    rec["status"] = "ACTIVE"
    rec["consecutive_undeliverable_count"] = 0
    rec["suspension_reason_code"] = None
    rec["last_confirmation_at"] = db.now()
    rec["reinstated_count"] += 1
    db.touch(rec)

    voter_rec = db.voters.get(rec["voter_id"])
    if voter_rec is not None:
        voter_rec["permanent_absentee_active"] = True
        db.touch(voter_rec)

    logbook.append(
        None,
        "ENROLLMENT_REINSTATED",
        actor.role,
        actor.user_id,
        "PermanentAbsenteeEnrollment",
        rec["id"],
        "Permanent absentee enrollment reinstated (%s)." % confirmation_evidence_type,
    )
    return response.record_response(rec)


@bp.delete("/permanent-absentee-enrollments/<enrollment_id>")
def remove_enrollment(enrollment_id):
    mw.require_roles("ElectionsClerk")
    rec = lookups.enrollment(enrollment_id)
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_ENROLLMENT_NOT_SUSPENDED")
    rec["status"] = "REMOVED"
    db.touch(rec)
    voter_rec = db.voters.get(rec["voter_id"])
    if voter_rec is not None:
        voter_rec["permanent_absentee_active"] = False
        db.touch(voter_rec)
    return response.record_response(rec)
