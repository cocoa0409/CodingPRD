"""Match, MatchMeeting, ActivityLog, ExitTransition and related endpoints
(PRD §3.5, §3.6, §3.7)."""
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
from store import create, get_or_404, paginate, sort_key, touch
import validate as V

bp = Blueprint("matches", __name__)

ACTIVITY_TYPES = {"OUTING", "CALL", "MEAL", "TUTORING", "EVENT"}
EXIT_TYPES = {"SUCCESSFUL_CLOSURE", "EARLY_TERMINATION"}
INITIATED_BY = {"BIG", "LITTLE", "GUARDIAN", "AGENCY"}
REASON_CODES = {"GRADUATION", "RELOCATION", "LOST_INTEREST", "SAFETY_CONCERN", "PROGRAM_VIOLATION"}
PARTIES = {"BIG", "LITTLE", "GUARDIAN"}


# --- Match read/list ---
@bp.route("/matches/<mid>", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def get_match(mid):
    rec = get_or_404(db.matches, mid, "Match")
    return object_response(serialize.match(rec))


@bp.route("/matches", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_matches():
    limit, offset = V.parse_pagination(request.args)
    rel = request.args.get("relationship_status")
    comp = request.args.get("compliance_status")
    vol = request.args.get("volunteer_id")
    items = list(db.matches.values())
    if rel is not None:
        items = [r for r in items if r["relationship_status"] == rel]
    if vol is not None:
        items = [r for r in items if r["volunteer_id"] == vol]
    if comp is not None:
        items = [r for r in items if domain.compliance_status(r) == comp]
    window, total = paginate(items, limit, offset)
    return array_response([serialize.match(r) for r in window], limit, offset, total)


# --- MatchMeeting scheduling + overlap guards ---
def _per_match_overlap(match_id, new_start, new_end, exclude_id=None):
    """Half-open [start, end) overlap against SCHEDULED/HELD meetings on the same
    match. Shared endpoints are back-to-back, not overlaps (PRD §3.5)."""
    for m in domain.meetings_for_match(match_id):
        if exclude_id is not None and m["id"] == exclude_id:
            continue
        if m["status"] not in ("SCHEDULED", "HELD"):
            continue
        if new_start < m["scheduled_end"] and m["scheduled_start"] < new_end:
            return True
    return False


def _per_guardian_double_booked(guardian_id, new_start, new_end):
    """Closed, buffer-inflated overlap across every SCHEDULED/HELD meeting of all
    matches of every child of this guardian (PRD §3.5)."""
    buffer = timedelta(minutes=calc.MEETING_BUFFER_MINUTES)
    # All children of this guardian.
    child_ids = {c["id"] for c in db.children.values() if c["guardian_id"] == guardian_id}
    # All matches whose child belongs to this guardian.
    match_ids = {m["id"] for m in db.matches.values() if m["child_id"] in child_ids}
    for meeting in db.match_meetings.values():
        if meeting["match_id"] not in match_ids:
            continue
        if meeting["status"] not in ("SCHEDULED", "HELD"):
            continue
        if (new_start < meeting["scheduled_end"] + buffer) and (
            meeting["scheduled_start"] < new_end + buffer
        ):
            return True
    return False


@bp.route("/matches/<mid>/meetings", methods=["POST"])
@require("MatchSpecialist")
def create_meeting(mid):
    match = get_or_404(db.matches, mid, "Match")
    body = V.get_body()
    scheduled_start = V.require_datetime(body, "scheduled_start")
    scheduled_end = V.require_datetime(body, "scheduled_end")
    location = V.require_str(body, "location")
    # Temporal window validity (422).
    if not (scheduled_end > scheduled_start):
        err("ERR_MEETING_WINDOW_INVALID", "scheduled_end must be strictly after scheduled_start")
    # Per-match overlap (409).
    if _per_match_overlap(mid, scheduled_start, scheduled_end):
        err("ERR_MEETING_OVERLAP", "Meeting overlaps an existing meeting on this match")
    # Per-guardian double-booking (409).
    child = db.children.get(match["child_id"])
    guardian_id = child["guardian_id"] if child is not None else None
    if guardian_id is not None and _per_guardian_double_booked(guardian_id, scheduled_start, scheduled_end):
        err("ERR_GUARDIAN_DOUBLE_BOOKED", "Meeting violates the guardian double-booking buffer")
    rec = create(
        {
            "match_id": mid,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "location": location,
            "status": "SCHEDULED",
            "outcome_notes": None,
        },
        db.match_meetings,
        "MatchMeeting",
    )
    return object_response(serialize.match_meeting(rec), 201)


@bp.route("/matches/<mid>/meetings", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_match_meetings(mid):
    get_or_404(db.matches, mid, "Match")
    items = domain.meetings_for_match(mid)
    ordered = sorted(items, key=sort_key)
    return array_response([serialize.match_meeting(r) for r in ordered], 10, 0, len(ordered))


# --- ActivityLog ---
@bp.route("/matches/<mid>/activities", methods=["POST"])
@require("MatchSpecialist", "Supervisor")
def create_activity(mid):
    match = get_or_404(db.matches, mid, "Match")
    body = V.get_body()
    occurred_at = V.require_datetime(body, "occurred_at")
    duration_minutes = V.require_int(body, "duration_minutes", minimum=1)
    activity_type = V.require_enum(body, "activity_type", ACTIVITY_TYPES)
    # Activity tracking applies once a match is ACTIVE (PRD §3.6).
    if match["relationship_status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Activities may only be appended to an ACTIVE match")
    rec = create(
        {
            "match_id": mid,
            "occurred_at": occurred_at,
            "duration_minutes": duration_minutes,
            "activity_type": activity_type,
            "status": "LOGGED",
        },
        db.activity_logs,
        "ActivityLog",
    )
    domain.recompute_match_activity_rollups(match)
    touch(match)
    return object_response(serialize.activity_log(rec), 201)


@bp.route("/matches/<mid>/activities", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_match_activities(mid):
    get_or_404(db.matches, mid, "Match")
    limit, offset = V.parse_pagination(request.args)
    items = domain.activities_for_match(mid)
    window, total = paginate(items, limit, offset)
    return array_response([serialize.activity_log(r) for r in window], limit, offset, total)


# --- ExitTransition ---
@bp.route("/matches/<mid>/exit-transitions", methods=["POST"])
@require("Supervisor", "MatchSpecialist")
def create_exit(mid):
    match = get_or_404(db.matches, mid, "Match")
    body = V.get_body()
    exit_type = V.require_enum(body, "exit_type", EXIT_TYPES)
    initiated_by = V.require_enum(body, "initiated_by", INITIATED_BY)
    reason_code = V.require_enum(body, "reason_code", REASON_CODES)
    # survey_required pinned at open: true iff SUCCESSFUL_CLOSURE or the match
    # has reached ACTIVE at any point (activated_at not null) (PRD §3.7).
    survey_required = (exit_type == "SUCCESSFUL_CLOSURE") or (match["activated_at"] is not None)
    rec = create(
        {
            "match_id": mid,
            "exit_type": exit_type,
            "initiated_by": initiated_by,
            "reason_code": reason_code,
            "status": "DRAFT",
            "survey_required": survey_required,
        },
        db.exit_transitions,
        "ExitTransition",
    )
    return object_response(serialize.exit_transition(rec), 201)


@bp.route("/matches/<mid>/exit-transitions", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_match_exits(mid):
    get_or_404(db.matches, mid, "Match")
    items = [e for e in db.exit_transitions.values() if e["match_id"] == mid]
    ordered = sorted(items, key=sort_key)
    return array_response([serialize.exit_transition(r) for r in ordered], 10, 0, len(ordered))


@bp.route("/matches/<mid>/supervision-contacts", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_match_contacts(mid):
    get_or_404(db.matches, mid, "Match")
    items = domain.contacts_for_match(mid)
    ordered = sorted(items, key=sort_key)
    return array_response([serialize.supervision_contact(r) for r in ordered], 10, 0, len(ordered))


@bp.route("/matches/<mid>/survey", methods=["GET"])
@require("Coordinator", "MatchSpecialist", "Supervisor")
def list_match_survey(mid):
    get_or_404(db.matches, mid, "Match")
    items = [s for s in db.outcome_surveys.values() if s["match_id"] == mid]
    ordered = sorted(items, key=sort_key)
    return array_response([serialize.outcome_survey(r) for r in ordered], 10, 0, len(ordered))
