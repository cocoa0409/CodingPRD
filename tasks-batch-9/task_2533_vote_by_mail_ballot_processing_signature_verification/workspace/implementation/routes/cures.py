"""Cure notices, evidence submissions, and adjudication."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import (
    CURE_OUTCOMES,
    DEFICIENCY_REASON_CODES,
    EVIDENCE_TYPES,
    SUBMISSION_CHANNELS,
)
from errors import ApiError
from services import accountability, cure, logbook, posture

bp = Blueprint("cures", __name__)

READ_ROLES = ("ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor")


@bp.post("/return-envelopes/<envelope_id>/cure-notices")
def issue_cure_notice(envelope_id):
    actor = mw.require_roles("ElectionsClerk")
    mw.body()
    env = lookups.envelope(envelope_id)
    election_rec = lookups.election_of_envelope(env)
    posture.require(election_rec, ("RECEIVING",))

    if env["signature_status"] != "CURE_REQUIRED":
        raise ApiError("ERR_ENVELOPE_SIGNATURE_STATE_INVALID")
    for existing in db.cure_notices.values():
        if existing["return_envelope_id"] == env["id"] and existing["status"] in (
            "ISSUED",
            "UNDER_EVIDENCE_REVIEW",
        ):
            raise ApiError("ERR_CURE_STATE_INVALID")

    notice = db.make_record(
        db.cure_notices,
        {
            "return_envelope_id": env["id"],
            "reason_code": env.get("_cure_reason_code"),
            "status": "ISSUED",
            "issued_at": db.now(),
            "cure_deadline_at": None,
            "open_cure_count_at_issue": 0,
            "canvass_days_at_issue": 0,
            "evidence_submission_count": 0,
            "deficiency_count": 0,
            "resolved_at": None,
        },
    )
    deadline, canvass_days, open_count = cure.derive_deadline(election_rec)
    notice["cure_deadline_at"] = deadline
    notice["canvass_days_at_issue"] = canvass_days
    notice["open_cure_count_at_issue"] = open_count

    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "CURE_ISSUED",
        actor.role,
        actor.user_id,
        "CureNotice",
        notice["id"],
        "Cure notice issued (%s)." % notice["reason_code"],
    )
    return response.record_response(notice, 201)


@bp.get("/cure-notices/<notice_id>")
def get_notice(notice_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.cure_notice(notice_id))


@bp.get("/cure-notices")
def list_notices():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.cure_notices.values()), ["return_envelope_id", "status"]
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/cure-notices/<notice_id>/evidence")
def submit_evidence(notice_id):
    mw.require_roles("ElectionsClerk")
    payload = mw.body()
    evidence_type = mw.require_enum(payload, "evidence_type", EVIDENCE_TYPES)
    submission_channel = mw.require_enum(
        payload, "submission_channel", SUBMISSION_CHANNELS
    )
    affirmation_signed = mw.require_bool(payload, "affirmation_signed")

    notice = lookups.cure_notice(notice_id)
    election_rec = lookups.election_of_notice(notice)
    posture.require_not_certified(election_rec)

    if notice["status"] != "ISSUED":
        raise ApiError("ERR_CURE_STATE_INVALID")
    if db.now() > notice["cure_deadline_at"]:
        raise ApiError("ERR_CURE_DEADLINE_PASSED")

    evidence = db.make_record(
        db.cure_evidence,
        {
            "cure_notice_id": notice["id"],
            "evidence_type": evidence_type,
            "submission_channel": submission_channel,
            "affirmation_signed": affirmation_signed,
            "received_at": db.now(),
            "accepted": None,
            "deficiency_reason_code": None,
        },
        common=False,
    )
    notice["evidence_submission_count"] += 1
    notice["status"] = "UNDER_EVIDENCE_REVIEW"
    db.touch(notice)
    accountability.recompute(election_rec)
    return response.record_response(evidence, 201)


@bp.post("/cure-notices/<notice_id>/adjudicate")
def adjudicate_cure(notice_id):
    actor = mw.require_roles("CanvassSupervisor")
    payload = mw.body()
    outcome = mw.require_enum(payload, "outcome", CURE_OUTCOMES)
    deficiency_reason_code = mw.optional_enum(
        payload, "deficiency_reason_code", DEFICIENCY_REASON_CODES, None
    )

    notice = lookups.cure_notice(notice_id)
    election_rec = lookups.election_of_notice(notice)
    posture.require_not_certified(election_rec)

    if notice["status"] != "UNDER_EVIDENCE_REVIEW":
        raise ApiError("ERR_CURE_STATE_INVALID")

    newest = cure.newest_evidence(notice)
    env = db.return_envelopes.get(notice["return_envelope_id"])

    if outcome == "CURE":
        if newest is None or not newest["affirmation_signed"]:
            raise ApiError("ERR_CURE_STATE_INVALID")
        if db.now() > notice["cure_deadline_at"]:
            raise ApiError("ERR_CURE_DEADLINE_PASSED")

        notice["status"] = "CURED"
        notice["resolved_at"] = db.now()
        db.touch(notice)
        newest["accepted"] = True
        if env is not None and env["signature_status"] == "CURE_REQUIRED":
            env["signature_status"] = "ACCEPTED"
            db.touch(env)
        accountability.recompute(election_rec)
        logbook.append(
            election_rec,
            "CURE_ADJUDICATED",
            actor.role,
            actor.user_id,
            "CureNotice",
            notice["id"],
            "Cure evidence accepted; notice cured.",
        )
        return response.record_response(notice)

    if newest is not None:
        newest["accepted"] = False
        newest["deficiency_reason_code"] = deficiency_reason_code
    notice["deficiency_count"] += 1
    notice["status"] = "ISSUED"
    db.touch(notice)
    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "CURE_ADJUDICATED",
        actor.role,
        actor.user_id,
        "CureNotice",
        notice["id"],
        "Cure evidence found deficient; notice returned to ISSUED.",
    )
    return response.record_response(notice)


@bp.get("/cure-evidence/<evidence_id>")
def get_evidence(evidence_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.cure_evidence(evidence_id))


@bp.get("/cure-evidence")
def list_evidence():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(list(db.cure_evidence.values()), ["cure_notice_id"])
    return response.list_response(db.ordered(rows), limit, offset)
