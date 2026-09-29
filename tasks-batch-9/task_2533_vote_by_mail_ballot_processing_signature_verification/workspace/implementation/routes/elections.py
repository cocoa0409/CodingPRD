"""Election registration, posture, accountability, and the canvass checkpoint."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import CANVASS_DAYS_STANDARD, POSTURES
from errors import ApiError
from services import (
    accountability,
    cascade,
    election_flow,
    logbook,
    posture,
    timeliness,
)

bp = Blueprint("elections", __name__)

READ_ROLES = (
    "ElectionsAdmin",
    "ElectionsClerk",
    "CanvassSupervisor",
    "SignatureReviewer",
    "Observer",
)
LIST_ROLES = ("ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor", "Observer")


@bp.post("/elections")
def create_election():
    actor = mw.require_roles("ElectionsAdmin")
    payload = mw.body()
    name = mw.require_string(payload, "name")
    election_date = mw.require_date(payload, "election_date")
    uocava_send_deadline_date = mw.require_date(payload, "uocava_send_deadline_date")
    domestic_send_deadline_date = mw.require_date(payload, "domestic_send_deadline_date")
    return_deadline_at = mw.require_datetime(payload, "return_deadline_at")
    postmark_grace_days = mw.optional_int(payload, "postmark_grace_days", 7, minimum=0)
    cure_window_days = mw.optional_int(payload, "cure_window_days", 21, minimum=0)
    postage_budget_cents = mw.require_int(payload, "postage_budget_cents", minimum=0)

    return_deadline_at = db.whole_second(return_deadline_at)
    rec = db.make_record(
        db.elections,
        {
            "name": name,
            "election_date": election_date,
            "uocava_send_deadline_date": uocava_send_deadline_date,
            "domestic_send_deadline_date": domestic_send_deadline_date,
            "return_deadline_at": return_deadline_at,
            "postmark_grace_days": postmark_grace_days,
            "cure_window_days": cure_window_days,
            "postage_budget_cents": postage_budget_cents,
            "posture": "PRE_MAIL",
            "packets_mailed_count": 0,
            "envelopes_received_count": 0,
            "outstanding_packet_count": 0,
            "undeliverable_packet_count": 0,
            "countable_envelope_count": 0,
            "attributable_ballot_count": 0,
            "rejected_envelope_count": 0,
            "provisional_referral_count": 0,
            "open_cure_count": 0,
            "canvass_days": CANVASS_DAYS_STANDARD,
            "canvass_lock_at": db.whole_second(
                db.add_days(return_deadline_at, CANVASS_DAYS_STANDARD)
            ),
            "postage_committed_cents": 0,
            "postage_actual_cents": 0,
            "reconciliation_status": "IN_BALANCE",
            "separation_run_sequence": 0,
            "canvass_sweep_index": 0,
        },
    )
    return response.record_response(rec, 201)


@bp.get("/elections/<election_id>")
def get_election(election_id):
    mw.require_roles(*READ_ROLES)
    rec = lookups.election(election_id)
    accountability.recompute(rec)
    return response.record_response(rec)


@bp.get("/elections")
def list_elections():
    mw.require_roles(*LIST_ROLES)
    limit, offset = mw.pagination()
    rows = list(db.elections.values())
    for rec in rows:
        accountability.recompute(rec)
    rows = mw.apply_filters(rows, ["posture"])
    return response.list_response(db.ordered(rows), limit, offset)


@bp.get("/elections/<election_id>/accountability")
def read_accountability(election_id):
    mw.require_roles(*LIST_ROLES)
    rec = lookups.election(election_id)
    return response.object_response(accountability.accountability_read(rec))


@bp.post("/elections/<election_id>/posture-advance")
def advance_posture(election_id):
    actor = mw.require_roles("ElectionsAdmin")
    payload = mw.body()
    target = mw.require_enum(payload, "target_posture", POSTURES)
    rec = lookups.election(election_id)
    accountability.recompute(rec)

    current = rec["posture"]
    expected = posture.successor(current)
    if expected is None or target != expected:
        raise ApiError("ERR_ELECTION_POSTURE_FORBIDS")

    if target == "CERTIFIED":
        if rec["reconciliation_status"] != "IN_BALANCE":
            raise ApiError("ERR_ELECTION_POSTURE_FORBIDS")
        if rec["open_cure_count"] != 0:
            raise ApiError("ERR_ELECTION_POSTURE_FORBIDS")
        challenged = sum(
            1 for e in lookups.envelopes_of_election(rec)
            if e["challenge_status"] == "CHALLENGED"
        )
        if challenged != 0:
            raise ApiError("ERR_ELECTION_POSTURE_FORBIDS")

    election_flow.apply_advance(rec, target, actor.role, actor.user_id)
    accountability.recompute(rec)
    return response.record_response(rec)


@bp.post("/elections/<election_id>/canvass-sweep")
def canvass_sweep(election_id):
    actor = mw.require_roles("ElectionsAdmin")
    mw.body()
    rec = lookups.election(election_id)
    posture.require_not_certified(rec)

    rec["canvass_sweep_index"] += 1
    db.touch(rec)

    now = db.now()
    expired_cure_count = 0
    sequestered = set()
    rejected = set()

    # Job one: expire overdue cures and drive the rejection cascade.
    notices = db.ordered(lookups.notices_of_election(rec))
    for notice in notices:
        if notice["status"] not in ("ISSUED", "UNDER_EVIDENCE_REVIEW"):
            continue
        if not notice["cure_deadline_at"] < now:
            continue
        notice["status"] = "EXPIRED"
        notice["resolved_at"] = now
        db.touch(notice)
        expired_cure_count += 1
        for evidence in db.ordered(
            [e for e in db.cure_evidence.values() if e["cure_notice_id"] == notice["id"]]
        ):
            if evidence["accepted"] is None:
                evidence["accepted"] = False
                if evidence["deficiency_reason_code"] is None:
                    evidence["deficiency_reason_code"] = "ILLEGIBLE"
        logbook.append(
            rec, "CURE_EXPIRED", actor.role, actor.user_id, "CureNotice",
            notice["id"], "Cure notice expired at the canvass checkpoint.",
        )
        env = db.return_envelopes.get(notice["return_envelope_id"])
        if env is None:
            continue
        if env["signature_status"] == "CURE_REQUIRED":
            env["signature_status"] = "REJECTED"
            db.touch(env)
            rejected.add(env["id"])
            if env["custody_status"] == "SEALED":
                env["custody_status"] = "SEQUESTERED"
                db.touch(env)
                sequestered.add(env["id"])
            voter_rec = lookups.voter_of_envelope(env)
            cascade.refer_to_provisional(
                voter_rec, rec, actor.role, actor.user_id,
                "Voter referred to the provisional process after cure expiry.",
            )
    accountability.recompute(rec)

    # Job two: write the FINAL timeliness variant.
    finalized_envelope_count = 0
    for env in db.ordered(lookups.envelopes_of_election(rec)):
        if env["custody_status"] == "SUPERSEDED_BY_REMAKE":
            continue
        verdict = timeliness.evaluate(env, rec, "FINAL")
        env["final_timeliness"] = verdict
        db.touch(env)
        finalized_envelope_count += 1
        # Job three: sequester the untimely.
        if verdict == "UNTIMELY" and env["custody_status"] == "SEALED":
            env["custody_status"] = "SEQUESTERED"
            db.touch(env)
            sequestered.add(env["id"])

    # Job four: close stale floor access.
    closed_observer_session_count = 0
    for session in db.ordered(
        [s for s in db.observer_sessions.values() if s["election_id"] == rec["id"]]
    ):
        if session["status"] != "CHECKED_IN":
            continue
        if session["window_end_at"] <= now:
            session["status"] = "CLOSED"
            db.touch(session)
            closed_observer_session_count += 1

    # Job five: recompute the accountability picture in full.
    accountability.recompute(rec)

    return response.object_response(
        {
            "canvass_sweep_index": rec["canvass_sweep_index"],
            "expired_cure_count": expired_cure_count,
            "finalized_envelope_count": finalized_envelope_count,
            "sequestered_envelope_count": len(sequestered),
            "rejected_envelope_count": len(rejected),
            "closed_observer_session_count": closed_observer_session_count,
            "reconciliation_status": rec["reconciliation_status"],
        }
    )
