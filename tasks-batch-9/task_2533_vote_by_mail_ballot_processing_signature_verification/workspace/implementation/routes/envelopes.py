"""Return-envelope intake, challenges, counting, and separation runs."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import (
    BALLOT_SECRECY_MIN_POOL,
    CHALLENGE_OUTCOMES,
    CHALLENGE_REASON_CODES,
    INTAKE_CHANNELS,
)
from errors import ApiError
from services import (
    accountability,
    cascade,
    election_flow,
    logbook,
    posture,
    timeliness,
)

bp = Blueprint("envelopes", __name__)

READ_ROLES = (
    "ElectionsAdmin",
    "ElectionsClerk",
    "CanvassSupervisor",
    "SignatureReviewer",
)


@bp.post("/return-envelopes")
def log_return_envelope():
    actor = mw.require_roles("ElectionsClerk")
    payload = mw.body()
    ballot_packet_id = mw.require_string(payload, "ballot_packet_id")
    intake_channel = mw.require_enum(payload, "intake_channel", INTAKE_CHANNELS)
    postmark_date = mw.optional_date(payload, "postmark_date", None)
    postmark_legible = mw.optional_bool(payload, "postmark_legible", True)

    packet = lookups.ballot_packet(ballot_packet_id)
    election_rec = lookups.election_of_packet(packet)
    posture.require(election_rec, ("MAILING", "RECEIVING"))

    if packet["status"] not in ("MAILED", "RETURNED"):
        raise ApiError("ERR_PACKET_STATE_INVALID")

    for existing in db.return_envelopes.values():
        if (
            existing["ballot_packet_id"] == packet["id"]
            and existing["remade_from_envelope_id"] is None
        ):
            raise ApiError("ERR_DUPLICATE_ENVELOPE_FOR_PACKET")

    env = db.make_record(
        db.return_envelopes,
        {
            "ballot_packet_id": packet["id"],
            "remade_from_envelope_id": None,
            "intake_channel": intake_channel,
            "postmark_date": postmark_date,
            "postmark_legible": postmark_legible,
            "received_at": db.now(),
            "preliminary_timeliness": None,
            "final_timeliness": None,
            "signature_status": "UNVERIFIED",
            "custody_status": "SEALED",
            "challenge_status": "NONE",
            "review_round_count": 0,
            "resolved_signature_confidence": None,
            "separation_run_sequence": None,
            "challenge_reason_code": None,
            "challenge_findings": None,
        },
    )
    env["preliminary_timeliness"] = timeliness.evaluate(env, election_rec, "PRELIMINARY")

    if packet["status"] == "MAILED":
        packet["status"] = "RETURNED"
        db.touch(packet)
        accountability.recompute_batch(db.mailing_batches.get(packet["mailing_batch_id"]))

    accountability.recompute(election_rec)
    election_flow.auto_advance(election_rec, "MAILING", "RECEIVING")
    logbook.append(
        election_rec,
        "ENVELOPE_INTAKE",
        actor.role,
        actor.user_id,
        "ReturnEnvelope",
        env["id"],
        "Returned ballot envelope logged (%s)." % intake_channel,
    )
    return response.record_response(env, 201)


@bp.get("/return-envelopes/<envelope_id>")
def get_envelope(envelope_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.envelope(envelope_id))


@bp.get("/return-envelopes")
def list_envelopes():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.return_envelopes.values()),
        [
            "ballot_packet_id",
            "remade_from_envelope_id",
            "signature_status",
            "custody_status",
            "challenge_status",
        ],
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/return-envelopes/<envelope_id>/challenges")
def file_challenge(envelope_id):
    actor = mw.require_roles("Observer")
    payload = mw.body()
    challenge_reason_code = mw.require_enum(
        payload, "challenge_reason_code", CHALLENGE_REASON_CODES
    )
    env = lookups.envelope(envelope_id)
    election_rec = lookups.election_of_envelope(env)
    posture.require_not_certified(election_rec)

    if env["challenge_status"] != "NONE":
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    if env["custody_status"] not in ("SEALED", "SEQUESTERED"):
        raise ApiError("ERR_ENVELOPE_CUSTODY_STATE_INVALID")

    now = db.now()
    holds_access = False
    for session in db.observer_sessions.values():
        if election_rec is None or session["election_id"] != election_rec["id"]:
            continue
        if session["observer_user_id"] != actor.user_id:
            continue
        if session["status"] != "CHECKED_IN":
            continue
        if not (session["window_start_at"] <= now < session["window_end_at"]):
            continue
        if session["station_area"] not in ("INTAKE", "SIGNATURE_REVIEW"):
            continue
        holds_access = True
        break
    if not holds_access:
        raise ApiError("ERR_OBSERVER_SESSION_REQUIRED")

    env["challenge_status"] = "CHALLENGED"
    env["challenge_reason_code"] = challenge_reason_code
    if env["custody_status"] == "SEALED":
        env["custody_status"] = "SEQUESTERED"
    db.touch(env)
    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "CHALLENGE_FILED",
        "Observer",
        actor.user_id,
        "ReturnEnvelope",
        env["id"],
        "Observer challenge filed (%s)." % challenge_reason_code,
    )
    return response.record_response(env)


@bp.post("/return-envelopes/<envelope_id>/challenge-adjudication")
def adjudicate_challenge(envelope_id):
    actor = mw.require_roles("CanvassSupervisor")
    payload = mw.body()
    outcome = mw.require_enum(payload, "outcome", CHALLENGE_OUTCOMES)
    challenge_findings = mw.require_string(payload, "challenge_findings")

    env = lookups.envelope(envelope_id)
    election_rec = lookups.election_of_envelope(env)
    posture.require_not_certified(election_rec)

    if env["challenge_status"] != "CHALLENGED":
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")

    env["challenge_findings"] = challenge_findings
    if outcome == "SUSTAIN":
        env["challenge_status"] = "SUSTAINED"
        env["signature_status"] = "REJECTED"
        db.touch(env)
        accountability.recompute(election_rec)
        logbook.append(
            election_rec,
            "CHALLENGE_ADJUDICATED",
            actor.role,
            actor.user_id,
            "ReturnEnvelope",
            env["id"],
            "Observer challenge sustained.",
        )
        cascade.refer_to_provisional(
            lookups.voter_of_envelope(env),
            election_rec,
            actor.role,
            actor.user_id,
            "Voter referred to the provisional process after a sustained challenge.",
        )
        return response.record_response(env)

    env["challenge_status"] = "OVERRULED"
    if (
        env["custody_status"] == "SEQUESTERED"
        and env["signature_status"] == "ACCEPTED"
        and env["final_timeliness"] != "UNTIMELY"
    ):
        env["custody_status"] = "SEALED"
    db.touch(env)
    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "CHALLENGE_ADJUDICATED",
        actor.role,
        actor.user_id,
        "ReturnEnvelope",
        env["id"],
        "Observer challenge overruled.",
    )
    return response.record_response(env)


@bp.post("/return-envelopes/<envelope_id>/count")
def count_envelope(envelope_id):
    mw.require_roles("CanvassSupervisor")
    mw.body()
    env = lookups.envelope(envelope_id)
    election_rec = lookups.election_of_envelope(env)
    posture.require_not_certified(election_rec)

    if env["custody_status"] != "SEPARATED":
        raise ApiError("ERR_ENVELOPE_CUSTODY_STATE_INVALID")
    if env["challenge_status"] not in ("NONE", "OVERRULED"):
        raise ApiError("ERR_CHALLENGE_STATE_INVALID")
    if env["final_timeliness"] not in ("TIMELY", "TIMELY_BY_POSTMARK"):
        raise ApiError("ERR_ENVELOPE_CUSTODY_STATE_INVALID")

    env["custody_status"] = "COUNTED"
    db.touch(env)
    accountability.recompute(election_rec)
    return response.record_response(env)


@bp.post("/elections/<election_id>/separation-runs")
def separation_run(election_id):
    actor = mw.require_roles("CanvassSupervisor")
    payload = mw.body()
    raw_ids = mw.require_field(payload, "return_envelope_ids")
    if not isinstance(raw_ids, list) or any(not isinstance(x, str) for x in raw_ids):
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'return_envelope_ids' must be an array of strings."
        )

    election_rec = lookups.election(election_id)
    posture.require(election_rec, ("RECEIVING",))

    envelopes = [lookups.envelope(env_id) for env_id in raw_ids]

    # Each listed envelope must independently qualify (priority 6).
    for env in envelopes:
        if env["custody_status"] != "SEALED":
            raise ApiError("ERR_ENVELOPE_CUSTODY_STATE_INVALID")
        if env["signature_status"] != "ACCEPTED":
            raise ApiError("ERR_ENVELOPE_SIGNATURE_STATE_INVALID")
        if env["challenge_status"] == "CHALLENGED":
            raise ApiError("ERR_CHALLENGE_STATE_INVALID")
        if env["final_timeliness"] == "UNTIMELY":
            raise ApiError("ERR_ENVELOPE_CUSTODY_STATE_INVALID")

    if not raw_ids:
        raise ApiError("ERR_SEPARATION_SET_EMPTY")

    distinct = []
    seen = set()
    for env in envelopes:
        if env["id"] in seen:
            continue
        seen.add(env["id"])
        distinct.append(env)
    if len(distinct) < BALLOT_SECRECY_MIN_POOL:
        raise ApiError("ERR_BALLOT_SECRECY_POOL_TOO_SMALL")

    election_rec["separation_run_sequence"] += 1
    run_sequence = election_rec["separation_run_sequence"]
    db.touch(election_rec)

    for env in distinct:
        env["custody_status"] = "SEPARATED"
        env["separation_run_sequence"] = run_sequence
        db.touch(env)

    accountability.recompute(election_rec)
    logbook.append(
        election_rec,
        "SEPARATION_RUN",
        actor.role,
        actor.user_id,
        "Election",
        election_rec["id"],
        "Separation run %d separated %d envelopes." % (run_sequence, len(distinct)),
    )
    return response.object_response(
        {
            "election_id": election_rec["id"],
            "run_sequence": run_sequence,
            "separated_count": len(distinct),
            "secrecy_pool_size": len(raw_ids),
            "countable_envelope_count": election_rec["countable_envelope_count"],
            "attributable_ballot_count": election_rec["attributable_ballot_count"],
        }
    )
