"""Bipartisan remake sessions for damaged and duplicate ballots."""
from datetime import timedelta

from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import REMAKE_CHANGEOVER_BUFFER_MINUTES, REMAKE_REASON_CODES
from errors import ApiError
from services import accountability, logbook, posture, signature

bp = Blueprint("remakes", __name__)

READ_ROLES = ("ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor")
OCCUPYING_STATUSES = ("OPEN", "COMPLETED")
BUFFER = timedelta(minutes=REMAKE_CHANGEOVER_BUFFER_MINUTES)


def _double_booked(reviewer_id, start_at, end_at, exclude_id=None):
    """Closed-interval geometry widened by a 15-minute changeover buffer."""
    for rec in db.remake_records.values():
        if exclude_id is not None and rec["id"] == exclude_id:
            continue
        if rec["status"] not in OCCUPYING_STATUSES:
            continue
        if reviewer_id not in (
            rec["team_member_a_reviewer_id"],
            rec["team_member_b_reviewer_id"],
        ):
            continue
        if (start_at - BUFFER) <= rec["session_end_at"] and rec[
            "session_start_at"
        ] <= (end_at + BUFFER):
            return True
    return False


@bp.post("/return-envelopes/<envelope_id>/remakes")
def open_remake(envelope_id):
    mw.require_roles("CanvassSupervisor")
    payload = mw.body()
    member_a_id = mw.require_string(payload, "team_member_a_reviewer_id")
    member_b_id = mw.require_string(payload, "team_member_b_reviewer_id")
    reason_code = mw.require_enum(payload, "reason_code", REMAKE_REASON_CODES)
    session_start_at = mw.require_datetime(payload, "session_start_at")
    session_end_at = mw.require_datetime(payload, "session_end_at")
    expected_envelope_version = mw.require_int(payload, "expected_envelope_version")
    remade_serial = mw.optional_string(payload, "remade_serial", None)
    if session_end_at <= session_start_at:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'session_end_at' must be strictly later than 'session_start_at'.",
        )

    env = lookups.envelope(envelope_id)
    member_a = lookups.reviewer(member_a_id)
    member_b = lookups.reviewer(member_b_id)

    if expected_envelope_version != env["version"]:
        raise ApiError("ERR_STALE_ENVELOPE_VERSION")

    election_rec = lookups.election_of_envelope(env)
    posture.require_not_certified(election_rec)

    if env["custody_status"] not in ("SEALED", "SEQUESTERED"):
        raise ApiError("ERR_ENVELOPE_CUSTODY_STATE_INVALID")

    if member_a["id"] == member_b["id"] or (
        member_a["party_affiliation"] == member_b["party_affiliation"]
    ):
        raise ApiError("ERR_REMAKE_TEAM_NOT_BIPARTISAN")

    reviewer_ids_on_envelope = {
        r["reviewer_id"] for r in signature.reviews_of_envelope(env)
    }
    if (
        member_a["id"] in reviewer_ids_on_envelope
        or member_b["id"] in reviewer_ids_on_envelope
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    for member in (member_a, member_b):
        if _double_booked(member["id"], session_start_at, session_end_at):
            raise ApiError("ERR_REMAKE_TEAM_DOUBLE_BOOKED")

    rec = db.make_record(
        db.remake_records,
        {
            "original_envelope_id": env["id"],
            "team_member_a_reviewer_id": member_a["id"],
            "team_member_b_reviewer_id": member_b["id"],
            "reason_code": reason_code,
            "session_start_at": session_start_at,
            "session_end_at": session_end_at,
            "status": "OPEN",
            "remade_serial": remade_serial,
            "remade_envelope_id": None,
            "completed_at": None,
            "voided_reason_code": None,
        },
    )
    db.touch(env)
    return response.record_response(rec, 201)


@bp.get("/remake-records/<record_id>")
def get_remake(record_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.remake_record(record_id))


@bp.get("/remake-records")
def list_remakes():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.remake_records.values()),
        [
            "original_envelope_id",
            "remade_envelope_id",
            "team_member_a_reviewer_id",
            "team_member_b_reviewer_id",
            "status",
        ],
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/remake-records/<record_id>/complete")
def complete_remake(record_id):
    actor = mw.require_roles("CanvassSupervisor")
    payload = mw.body()
    supplied_serial = mw.optional_string(payload, "remade_serial", None)

    rec = lookups.remake_record(record_id)
    election_rec = lookups.election_of_remake(rec)
    original = db.return_envelopes.get(rec["original_envelope_id"])

    if rec["status"] != "OPEN":
        raise ApiError("ERR_REMAKE_STATE_INVALID")
    if original is None or original["custody_status"] not in ("SEALED", "SEQUESTERED"):
        raise ApiError("ERR_ENVELOPE_CUSTODY_STATE_INVALID")
    if original["challenge_status"] == "CHALLENGED":
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    posture.require(election_rec, ("RECEIVING", "CANVASS_LOCKED"))

    serial = supplied_serial if supplied_serial is not None else rec["remade_serial"]
    if serial is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'remade_serial' is required.")

    for other in db.remake_records.values():
        if other["id"] == rec["id"] or other["status"] != "COMPLETED":
            continue
        if other["remade_serial"] != serial:
            continue
        other_election = lookups.election_of_remake(other)
        if other_election is not None and election_rec is not None and (
            other_election["id"] == election_rec["id"]
        ):
            raise ApiError("ERR_DUPLICATE_REMAKE_SERIAL")

    # First link: mint the replacement envelope from the original's intake facts.
    replacement = db.make_record(
        db.return_envelopes,
        {
            "ballot_packet_id": original["ballot_packet_id"],
            "remade_from_envelope_id": original["id"],
            "intake_channel": original["intake_channel"],
            "postmark_date": original["postmark_date"],
            "postmark_legible": original["postmark_legible"],
            "received_at": original["received_at"],
            "preliminary_timeliness": original["preliminary_timeliness"],
            "final_timeliness": original["final_timeliness"],
            "signature_status": original["signature_status"],
            "custody_status": "SEALED",
            "challenge_status": "NONE",
            "review_round_count": 0,
            "resolved_signature_confidence": None,
            "separation_run_sequence": None,
            "challenge_reason_code": None,
            "challenge_findings": None,
        },
    )

    rec["status"] = "COMPLETED"
    rec["remade_serial"] = serial
    rec["remade_envelope_id"] = replacement["id"]
    rec["completed_at"] = db.now()
    db.touch(rec)

    original["_pre_remake_signature_status"] = original["signature_status"]
    original["custody_status"] = "SUPERSEDED_BY_REMAKE"
    db.touch(original)

    # Clean-ups: the cure and the review follow the replacement.
    for notice in db.ordered(
        [
            n for n in db.cure_notices.values()
            if n["return_envelope_id"] == original["id"]
            and n["status"] in ("ISSUED", "UNDER_EVIDENCE_REVIEW")
        ]
    ):
        notice["status"] = "WITHDRAWN"
        notice["resolved_at"] = db.now()
        db.touch(notice)

    for review in db.ordered(
        [
            r for r in db.signature_reviews.values()
            if r["return_envelope_id"] == original["id"] and r["status"] == "ASSIGNED"
        ]
    ):
        review["status"] = "VOIDED"
        db.touch(review)
        reviewer_rec = db.reviewers.get(review["reviewer_id"])
        if reviewer_rec is not None and reviewer_rec["active_review_count"] > 0:
            reviewer_rec["active_review_count"] -= 1
            db.touch(reviewer_rec)

    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "REMAKE_COMPLETED",
        actor.role,
        actor.user_id,
        "RemakeRecord",
        rec["id"],
        "Bipartisan remake completed; replacement serial %s minted." % serial,
    )
    return response.record_response(rec)


@bp.post("/remake-records/<record_id>/void")
def void_remake(record_id):
    actor = mw.require_roles("CanvassSupervisor")
    payload = mw.body()
    voided_reason_code = mw.require_string(payload, "voided_reason_code")

    rec = lookups.remake_record(record_id)
    election_rec = lookups.election_of_remake(rec)
    posture.require_not_certified(election_rec)

    if rec["status"] not in ("OPEN", "COMPLETED"):
        raise ApiError("ERR_REMAKE_STATE_INVALID")

    was_completed = rec["status"] == "COMPLETED"
    replacement = db.return_envelopes.get(rec["remade_envelope_id"])
    if was_completed:
        if replacement is not None and replacement["custody_status"] == "COUNTED":
            raise ApiError("ERR_REMAKE_STATE_INVALID")

    rec["voided_reason_code"] = voided_reason_code
    rec["status"] = "VOIDED"
    db.touch(rec)

    if was_completed:
        # Compensating action: withdraw the replacement, restore the original.
        if replacement is not None:
            replacement["signature_status"] = "REJECTED"
            replacement["custody_status"] = "SEQUESTERED"
            db.touch(replacement)
        original = db.return_envelopes.get(rec["original_envelope_id"])
        if original is not None:
            restored = original.get("_pre_remake_signature_status")
            if restored is not None:
                original["signature_status"] = restored
            original["custody_status"] = "SEALED"
            db.touch(original)

    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "REMAKE_VOIDED",
        actor.role,
        actor.user_id,
        "RemakeRecord",
        rec["id"],
        "Remake session voided (%s)." % voided_reason_code,
    )
    return response.record_response(rec)
