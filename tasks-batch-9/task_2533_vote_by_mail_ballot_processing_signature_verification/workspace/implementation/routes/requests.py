"""Ballot requests and address verification."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import (
    DELIVERY_METHODS,
    FORWARDING_CLASSES,
    NCOA_RESULTS,
    REQUEST_CHANNELS,
)
from errors import ApiError
from services import accountability, cascade, logbook, posture

bp = Blueprint("requests", __name__)

READ_ROLES = ("ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor")
SUPERSEDABLE = ("RECEIVED", "ADDRESS_HOLD", "ADDRESS_CLEARED", "APPROVED")


def _new_verification(request_rec):
    return db.make_record(
        db.address_verifications,
        {
            "ballot_request_id": request_rec["id"],
            "status": "PENDING",
            "ncoa_result": None,
            "verified_mailing_address": None,
            "forwardable": None,
            "evaluated_at": None,
        },
    )


def _fail_pending_verifications(request_rec):
    for verification in db.ordered(
        [
            v for v in db.address_verifications.values()
            if v["ballot_request_id"] == request_rec["id"] and v["status"] == "PENDING"
        ]
    ):
        verification["status"] = "FAILED"
        db.touch(verification)


@bp.post("/ballot-requests")
def create_ballot_request():
    actor = mw.require_roles("ElectionsClerk")
    payload = mw.body()
    voter_id = mw.require_string(payload, "voter_id")
    election_id = mw.require_string(payload, "election_id")
    request_channel = mw.require_enum(payload, "request_channel", REQUEST_CHANNELS)
    delivery_method = mw.require_enum(payload, "delivery_method", DELIVERY_METHODS)
    expected_voter_version = mw.require_int(payload, "expected_voter_version")
    permanent_flag = mw.optional_bool(payload, "permanent_flag", False)

    voter_rec = lookups.voter(voter_id)
    election_rec = lookups.election(election_id)

    if expected_voter_version != voter_rec["version"]:
        raise ApiError("ERR_STALE_VOTER_VERSION")

    posture.require(election_rec, ("PRE_MAIL", "MAILING"))

    if voter_rec["registration_status"] != "ACTIVE":
        raise ApiError("ERR_VOTER_REGISTRATION_INACTIVE")
    if delivery_method == "EMAIL_UOCAVA" and voter_rec["uocava_status"] == "NONE":
        raise ApiError("ERR_DELIVERY_METHOD_NOT_ELIGIBLE")

    snapshot = voter_rec["mailing_address"] or voter_rec["residence_address"]
    rec = db.make_record(
        db.ballot_requests,
        {
            "voter_id": voter_rec["id"],
            "election_id": election_rec["id"],
            "request_channel": request_channel,
            "delivery_method": delivery_method,
            "permanent_flag": permanent_flag,
            "status": "RECEIVED",
            "mailing_address_snapshot": snapshot,
            "forwarding_class": "UNKNOWN",
            "rejection_reason_code": None,
        },
    )
    _new_verification(rec)
    db.touch(voter_rec)

    # Supersede any earlier live request by the same voter for the same election.
    for older in db.ordered(list(db.ballot_requests.values())):
        if older["id"] == rec["id"]:
            continue
        if older["voter_id"] != voter_rec["id"]:
            continue
        if older["election_id"] != election_rec["id"]:
            continue
        if older["status"] not in SUPERSEDABLE:
            continue
        older["status"] = "SUPERSEDED"
        db.touch(older)
        _fail_pending_verifications(older)
        for packet in db.ordered(
            [
                p for p in db.ballot_packets.values()
                if p["ballot_request_id"] == older["id"] and p["status"] == "QUEUED"
            ]
        ):
            packet["status"] = "SPOILED"
            db.touch(packet)
            accountability.recompute_batch(db.mailing_batches.get(packet["mailing_batch_id"]))

    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "REQUEST_LOGGED",
        actor.role,
        actor.user_id,
        "Voter",
        voter_rec["id"],
        "Vote-by-mail ballot request logged.",
    )
    return response.record_response(rec, 201)


@bp.get("/ballot-requests/<request_id>")
def get_ballot_request(request_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.ballot_request(request_id))


@bp.get("/ballot-requests")
def list_ballot_requests():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.ballot_requests.values()), ["voter_id", "election_id", "status"]
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/ballot-requests/<request_id>/approve")
def approve_ballot_request(request_id):
    mw.require_roles("ElectionsClerk")
    mw.body()
    rec = lookups.ballot_request(request_id)
    election_rec = db.elections.get(rec["election_id"])
    posture.require(election_rec, ("PRE_MAIL", "MAILING"))

    if rec["status"] != "ADDRESS_CLEARED":
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    voter_rec = db.voters.get(rec["voter_id"])
    if voter_rec is None or voter_rec["registration_status"] != "ACTIVE":
        raise ApiError("ERR_VOTER_REGISTRATION_INACTIVE")

    rec["status"] = "APPROVED"
    db.touch(rec)

    if rec["permanent_flag"] and lookups.live_enrollment_of_voter(voter_rec) is None:
        db.make_record(
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

    return response.record_response(rec)


@bp.post("/ballot-requests/<request_id>/reject")
def reject_ballot_request(request_id):
    mw.require_roles("ElectionsClerk")
    payload = mw.body()
    rejection_reason_code = mw.require_string(payload, "rejection_reason_code")
    rec = lookups.ballot_request(request_id)
    posture.require_not_certified(db.elections.get(rec["election_id"]))

    if rec["status"] not in ("RECEIVED", "ADDRESS_HOLD", "ADDRESS_CLEARED"):
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    rec["status"] = "REJECTED"
    rec["rejection_reason_code"] = rejection_reason_code
    db.touch(rec)
    _fail_pending_verifications(rec)
    return response.record_response(rec)


@bp.post("/ballot-requests/<request_id>/address-recheck")
def address_recheck(request_id):
    mw.require_roles("ElectionsClerk")
    mw.body()
    rec = lookups.ballot_request(request_id)
    posture.require_not_certified(db.elections.get(rec["election_id"]))
    if rec["status"] != "ADDRESS_HOLD":
        raise ApiError("ERR_REQUEST_STATE_INVALID")
    verification = _new_verification(rec)
    return response.record_response(verification, 201)


@bp.get("/address-verifications/<verification_id>")
def get_verification(verification_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.address_verification(verification_id))


@bp.get("/address-verifications")
def list_verifications():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.address_verifications.values()), ["ballot_request_id", "status"]
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/address-verifications/<verification_id>/results")
def record_verification_result(verification_id):
    actor = mw.require_roles("ElectionsClerk")
    payload = mw.body()
    ncoa_result = mw.require_enum(payload, "ncoa_result", NCOA_RESULTS)
    verified_mailing_address = mw.optional_string(payload, "verified_mailing_address", None)
    forwardable = mw.optional_bool(payload, "forwardable", None)

    rec = lookups.address_verification(verification_id)
    request_rec = db.ballot_requests.get(rec["ballot_request_id"])
    election_rec = (
        db.elections.get(request_rec["election_id"]) if request_rec else None
    )
    posture.require_not_certified(election_rec)

    if rec["status"] != "PENDING":
        raise ApiError("ERR_VERIFICATION_ALREADY_RESOLVED")
    if request_rec is None or request_rec["status"] not in ("RECEIVED", "ADDRESS_HOLD"):
        raise ApiError("ERR_REQUEST_STATE_INVALID")

    rec["ncoa_result"] = ncoa_result
    rec["verified_mailing_address"] = verified_mailing_address
    rec["forwardable"] = forwardable
    rec["evaluated_at"] = db.now()

    if ncoa_result in ("MATCH_SAME", "MATCH_FORWARDABLE"):
        rec["status"] = "CLEARED"
        db.touch(rec)
        request_rec["status"] = "ADDRESS_CLEARED"
        request_rec["forwarding_class"] = (
            "SAME_ADDRESS" if ncoa_result == "MATCH_SAME" else "FORWARDABLE"
        )
        if ncoa_result == "MATCH_FORWARDABLE":
            request_rec["mailing_address_snapshot"] = verified_mailing_address
        db.touch(request_rec)
        return response.record_response(rec)

    rec["status"] = "FAILED"
    db.touch(rec)
    request_rec["status"] = "ADDRESS_HOLD"
    if ncoa_result == "MATCH_NON_FORWARDABLE":
        request_rec["forwarding_class"] = "NON_FORWARDABLE"
    # On NO_MATCH the forwarding class is left at UNKNOWN -- never written.
    db.touch(request_rec)

    if ncoa_result == "MATCH_NON_FORWARDABLE":
        voter_rec = db.voters.get(request_rec["voter_id"])
        cascade.undeliverable_event(
            voter_rec, election_rec, "ADDRESS_NON_FORWARDABLE", actor
        )
    return response.record_response(rec)
