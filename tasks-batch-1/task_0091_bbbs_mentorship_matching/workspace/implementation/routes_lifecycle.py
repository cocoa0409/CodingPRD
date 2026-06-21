"""Meeting actions, supervision-contact completion, exit finalize, and outcome
surveys (PRD §3.5, §3.6, §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import clock
import db
import domain
import serialize
from errors import err
from middleware import require
from response import array_response, object_response
from store import create, get_or_404, sort_key, touch
import validate as V

bp = Blueprint("lifecycle", __name__)

PARTIES = {"BIG", "LITTLE", "GUARDIAN"}


# --- MatchMeeting actions ---
@bp.route("/match-meetings/<mid>", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def get_meeting(mid):
    rec = get_or_404(db.match_meetings, mid, "MatchMeeting")
    return object_response(serialize.match_meeting(rec))


@bp.route("/match-meetings/<mid>/hold", methods=["POST"])
@require("MatchSpecialist")
def hold_meeting(mid):
    rec = get_or_404(db.match_meetings, mid, "MatchMeeting")
    body = V.get_body()
    # State precondition: meeting must be SCHEDULED.
    if rec["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Only a SCHEDULED meeting may be held")
    match = db.matches.get(rec["match_id"])
    # Business: parent match must be CONFIRMED.
    if match is None or match["relationship_status"] != "CONFIRMED":
        err("ERR_MATCH_NOT_READY_FOR_MEETING", "Parent match must be CONFIRMED to hold the meeting")
    if "outcome_notes" in body and body.get("outcome_notes") is not None:
        rec["outcome_notes"] = V.require_str(body, "outcome_notes")
    rec["status"] = "HELD"
    touch(rec)
    # Advance parent match CONFIRMED -> INTRODUCED.
    match["relationship_status"] = "INTRODUCED"
    touch(match)
    return object_response(serialize.match_meeting(rec))


@bp.route("/match-meetings/<mid>/no-show", methods=["POST"])
@require("MatchSpecialist")
def no_show_meeting(mid):
    rec = get_or_404(db.match_meetings, mid, "MatchMeeting")
    if rec["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "Only a SCHEDULED meeting may be marked no-show")
    rec["status"] = "NO_SHOW"
    touch(rec)
    return object_response(serialize.match_meeting(rec))


@bp.route("/match-meetings/<mid>/affirm", methods=["POST"])
@require("MatchSpecialist")
def affirm_meeting(mid):
    rec = get_or_404(db.match_meetings, mid, "MatchMeeting")
    if rec["status"] != "HELD":
        err("ERR_INVALID_STATE", "Only a HELD meeting may be affirmed")
    match = db.matches.get(rec["match_id"])
    rec["status"] = "AFFIRMED"
    touch(rec)
    # Advance parent match INTRODUCED -> ACTIVE; stamp activated_at; open the
    # first supervision follow-up (PRD §3.5).
    now = clock.now()
    match["relationship_status"] = "ACTIVE"
    match["activated_at"] = now
    touch(match)
    create(
        {
            "match_id": match["id"],
            "due_at": now + timedelta(days=calc.CONTACT_INTERVAL_DAYS),
            "contacted_at": None,
            "party": None,
            "concern_flag": False,
            "status": "OPEN",
        },
        db.supervision_contacts,
        "SupervisionContact",
    )
    return object_response(serialize.match_meeting(rec))


@bp.route("/match-meetings/<mid>/rescind", methods=["POST"])
@require("MatchSpecialist")
def rescind_meeting(mid):
    rec = get_or_404(db.match_meetings, mid, "MatchMeeting")
    if rec["status"] != "HELD":
        err("ERR_INVALID_STATE", "Only a HELD meeting may be rescinded")
    rec["status"] = "RESCINDED"
    touch(rec)
    # Parent match stays INTRODUCED (no change).
    return object_response(serialize.match_meeting(rec))


# --- SupervisionContact ---
@bp.route("/supervision-contacts/<cid>", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def get_contact(cid):
    rec = get_or_404(db.supervision_contacts, cid, "SupervisionContact")
    return object_response(serialize.supervision_contact(rec))


@bp.route("/supervision-contacts/<cid>/complete", methods=["POST"])
@require("Supervisor")
def complete_contact(cid):
    rec = get_or_404(db.supervision_contacts, cid, "SupervisionContact")
    body = V.get_body()
    contacted_at = V.require_datetime(body, "contacted_at")
    party = V.require_enum(body, "party", PARTIES)
    concern_flag = V.optional_bool(body, "concern_flag", default=False)
    # State precondition: contact must be OPEN.
    if rec["status"] != "OPEN":
        err("ERR_INVALID_STATE", "Only an OPEN supervision contact may be completed")
    match = db.matches.get(rec["match_id"])
    # Business: parent match must be ACTIVE.
    if match is None or match["relationship_status"] != "ACTIVE":
        err("ERR_MATCH_NOT_ACTIVE", "Parent match must be ACTIVE to complete a supervision contact")
    rec["status"] = "COMPLETED"
    rec["contacted_at"] = contacted_at
    rec["party"] = party
    rec["concern_flag"] = concern_flag
    touch(rec)
    # Open the next monthly follow-up.
    create(
        {
            "match_id": match["id"],
            "due_at": contacted_at + timedelta(days=calc.CONTACT_INTERVAL_DAYS),
            "contacted_at": None,
            "party": None,
            "concern_flag": False,
            "status": "OPEN",
        },
        db.supervision_contacts,
        "SupervisionContact",
    )
    # Recompute match last_contact_at (compliance derived at read).
    domain.recompute_match_contact_rollup(match)
    touch(match)
    return object_response(serialize.supervision_contact(rec))


# --- ExitTransition ---
@bp.route("/exit-transitions/<eid>", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def get_exit(eid):
    rec = get_or_404(db.exit_transitions, eid, "ExitTransition")
    return object_response(serialize.exit_transition(rec))


@bp.route("/exit-transitions/<eid>/survey", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_exit_survey(eid):
    get_or_404(db.exit_transitions, eid, "ExitTransition")
    items = [s for s in db.outcome_surveys.values() if s["exit_transition_id"] == eid]
    ordered = sorted(items, key=sort_key)
    return array_response([serialize.outcome_survey(r) for r in ordered], 10, 0, len(ordered))


@bp.route("/exit-transitions/<eid>/finalize", methods=["POST"])
@require("Supervisor")
def finalize_exit(eid):
    rec = get_or_404(db.exit_transitions, eid, "ExitTransition")
    # State precondition: exit must be DRAFT and parent match in INTRODUCED|ACTIVE.
    if rec["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Only a DRAFT exit may be finalized")
    match = db.matches.get(rec["match_id"])
    if match is None or match["relationship_status"] not in ("INTRODUCED", "ACTIVE"):
        err("ERR_INVALID_STATE", "Parent match must be INTRODUCED or ACTIVE to finalize the exit")
    # Segregation of duties: finalizing supervisor must differ from confirming
    # match specialist (PRD §3.7).
    acting = request.headers.get("X-User-ID")
    if match.get("_confirmed_by") is not None and acting == match["_confirmed_by"]:
        err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The finalizing supervisor cannot be the specialist who confirmed the match",
        )
    closed_from = match["relationship_status"]
    rec["status"] = "FINALIZED"
    touch(rec)
    domain.close_match(match, rec["exit_type"], closed_from)
    return object_response(serialize.exit_transition(rec))


# --- OutcomeSurvey ---
@bp.route("/outcome-surveys", methods=["POST"])
@require("Supervisor")
def create_survey():
    body = V.get_body()
    match_id = V.require_str(body, "match_id")
    exit_transition_id = V.require_str(body, "exit_transition_id")
    relationship_quality = V.require_int(body, "relationship_quality", minimum=1, maximum=5)
    child_outcome = V.require_int(body, "child_outcome", minimum=1, maximum=5)
    would_rematch = V.require_bool(body, "would_rematch")
    # Body FK existence (priority 3).
    match = db.matches.get(match_id)
    if match is None:
        err("ERR_NOT_FOUND", "Match %s not found" % match_id)
    exit_rec = db.exit_transitions.get(exit_transition_id)
    if exit_rec is None:
        err("ERR_NOT_FOUND", "ExitTransition %s not found" % exit_transition_id)
    # State precondition: parent match must be CLOSED.
    if match["relationship_status"] != "CLOSED":
        err("ERR_INVALID_STATE", "Match must be CLOSED before submitting the outcome survey")
    # Business: referenced exit's survey_required must be true.
    if not exit_rec["survey_required"]:
        err("ERR_SURVEY_NOT_REQUIRED", "The referenced exit does not require a survey")
    # Business: at most one survey per match_id.
    if any(s["match_id"] == match_id for s in db.outcome_surveys.values()):
        err("ERR_SURVEY_ALREADY_EXISTS", "A survey already exists for this match")
    composite, band = calc.outcome_composite(relationship_quality, child_outcome, would_rematch)
    rec = create(
        {
            "match_id": match_id,
            "exit_transition_id": exit_transition_id,
            "relationship_quality": relationship_quality,
            "child_outcome": child_outcome,
            "would_rematch": would_rematch,
            "composite_score": composite,
            "outcome_band": band,
        },
        db.outcome_surveys,
        "OutcomeSurvey",
    )
    return object_response(serialize.outcome_survey(rec), 201)


@bp.route("/outcome-surveys/<sid>", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def get_survey(sid):
    rec = get_or_404(db.outcome_surveys, sid, "OutcomeSurvey")
    return object_response(serialize.outcome_survey(rec))
