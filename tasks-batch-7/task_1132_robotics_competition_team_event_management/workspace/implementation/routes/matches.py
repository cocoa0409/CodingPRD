"""Match lifecycle, MatchScoreBreakdown, QueueSlot, FieldResetLog, projected ranking
(PRD 3.5)."""
from flask import Blueprint, request

from auth import require_roles
from db import store, stamp_new, stamp_new_breakdown, touch, now
from envelope import success, paginated
from errors import (
    ApiError,
    ERR_ALLIANCE_NOT_FOUND,
    ERR_DUPLICATE_MATCH_NUMBER,
    ERR_EVENT_WRONG_STATUS,
    ERR_FIELD_INTERVAL_VIOLATION,
    ERR_FIELD_NOT_RESET,
    ERR_INCOMPLETE_QUEUE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MATCH_NOT_QUEUED,
    ERR_NO_REPLAY_GROUNDS,
    ERR_SCORE_BREAKDOWN_MISSING,
    ERR_SEGREGATION_VIOLATION,
    ERR_TEAM_NOT_AT_FIELD,
    ERR_TEAM_NOT_FOUND,
)
from services import (
    FIELD_RESET_MIN_SECONDS,
    breakdown_for,
    compute_team_aggregates,
    recompute_match_teams,
    run_ranking_points,
    run_score_match,
)
from util import (
    TERMINAL,
    check_from_state,
    gate_posture,
    get_body,
    public,
    req_dt,
    req_enum,
    req_int,
    req_str,
    resolve_event,
    resolve_team,
    resolve_match,
    resolve_queue_slot,
    resolve_reset_log,
)

bp = Blueprint("matches", __name__)

MATCH_GET_ROLES = ("EventDirector", "Scorekeeper", "QueueManager", "HeadReferee", "FieldResetCrew", "TeamLead")
MATCH_SERIES = {"QUALIFICATION", "PLAYOFF"}
CARD_KINDS = {"NONE", "YELLOW", "RED"}
SLOT_POSITIONS = {"RED_1", "RED_2", "RED_3", "BLUE_1", "BLUE_2", "BLUE_3"}


def _alliance_members(alliance):
    return [
        tid for tid in (
            alliance.get("captain_team_id"),
            alliance.get("pick1_team_id"),
            alliance.get("pick2_team_id"),
        )
        if tid
    ]


# ---------------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------------

@bp.route("/frc-events/<eventId>/matches", methods=["POST"])
def create_match(eventId):
    require_roles("EventDirector", "Scorekeeper")
    event = resolve_event(eventId)
    gate_posture(event)
    body = get_body()
    match_number = req_int(body, "match_number", minimum=1)
    series = req_enum(body, "series", MATCH_SERIES)
    scheduled_at = req_dt(body, "scheduled_at")
    field_index = req_int(body, "field_index", minimum=1)
    red_alliance_id = req_str(body, "red_alliance_id")
    blue_alliance_id = req_str(body, "blue_alliance_id")
    if field_index > event["field_count"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "field_index exceeds the event field_count")
    for m in store.matches.values():
        if m["event_id"] == eventId and m["series"] == series and m["match_number"] == match_number:
            raise ApiError(ERR_DUPLICATE_MATCH_NUMBER, 409, "match_number %s already exists for this series" % match_number)
    red = store.alliances.get(red_alliance_id)
    if red is None or red["event_id"] != eventId:
        raise ApiError(ERR_ALLIANCE_NOT_FOUND, 404, "Alliance %s not found" % red_alliance_id)
    blue = store.alliances.get(blue_alliance_id)
    if blue is None or blue["event_id"] != eventId:
        raise ApiError(ERR_ALLIANCE_NOT_FOUND, 404, "Alliance %s not found" % blue_alliance_id)
    # PRD 2.5/3.4: no two consecutive matches on the same field may be
    # scheduled closer than FIELD_RESET_MIN_SECONDS = 300 seconds.
    for m in store.matches.values():
        if m["event_id"] != eventId or m["field_index"] != field_index:
            continue
        other_at = m.get("scheduled_at")
        if other_at is None:
            continue
        if abs((scheduled_at - other_at).total_seconds()) < FIELD_RESET_MIN_SECONDS:
            raise ApiError(
                ERR_FIELD_INTERVAL_VIOLATION, 422,
                "Matches on field %s must be at least %d seconds apart" % (field_index, FIELD_RESET_MIN_SECONDS),
            )
    match = {
        "event_id": eventId,
        "match_number": match_number,
        "series": series,
        "scheduled_at": scheduled_at,
        "field_index": field_index,
        "red_alliance_id": red_alliance_id,
        "blue_alliance_id": blue_alliance_id,
        "status": "SCHEDULED",
        "red_score": None,
        "blue_score": None,
        "red_ranking_points": None,
        "blue_ranking_points": None,
        "_red_teams": _alliance_members(red),
        "_blue_teams": _alliance_members(blue),
        "_scored_by": None,
    }
    stamp_new(match)
    store.matches[match["id"]] = match
    return success(public(match), code=201)


@bp.route("/frc-events/<eventId>/matches", methods=["GET"])
def list_matches(eventId):
    require_roles(*MATCH_GET_ROLES)
    event = resolve_event(eventId)
    items = [m for m in store.matches.values() if m["event_id"] == event["id"]]
    series = request.args.get("series")
    if series is not None:
        items = [m for m in items if m["series"] == series]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    field_index = request.args.get("field_index")
    if field_index is not None:
        try:
            fi = int(field_index)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "field_index must be an integer")
        items = [m for m in items if m["field_index"] == fi]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/matches/<matchId>", methods=["GET"])
def get_match(eventId, matchId):
    require_roles(*MATCH_GET_ROLES)
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    return success(public(match))


@bp.route("/frc-events/<eventId>/matches/<matchId>/queue", methods=["POST"])
def queue_match(eventId, matchId):
    require_roles("QueueManager")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    if event["status"] not in ("MATCHES_RUNNING", "ALLIANCE_SELECTION"):
        raise ApiError(ERR_EVENT_WRONG_STATUS, 409, "Matches can only be queued while MATCHES_RUNNING or ALLIANCE_SELECTION")
    gate_posture(event)
    check_from_state(match, "status", "SCHEDULED", TERMINAL["Match"], "Match")
    slots = [s for s in store.queue_slots.values() if s["match_id"] == matchId]
    if len(slots) != 6:
        raise ApiError(ERR_INCOMPLETE_QUEUE, 409, "All 6 queue slots must exist before queueing")
    for s in slots:
        if s["status"] != "STAGED":
            s["status"] = "STAGED"
            touch(s)
    match["status"] = "QUEUED"
    touch(match)
    return success(public(match))


@bp.route("/frc-events/<eventId>/matches/<matchId>/take-field", methods=["POST"])
def take_field(eventId, matchId):
    require_roles("QueueManager")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    gate_posture(event)
    check_from_state(match, "status", "QUEUED", TERMINAL["Match"], "Match")
    slots = [s for s in store.queue_slots.values() if s["match_id"] == matchId]
    if len(slots) != 6 or any(s["status"] != "AT_FIELD" for s in slots):
        raise ApiError(ERR_TEAM_NOT_AT_FIELD, 409, "All 6 queue slots must be AT_FIELD")
    # Prior FieldResetLog on the same field must be COMPLETE (or none exist).
    blocking = None
    for log in store.reset_logs.values():
        other = store.matches.get(log["match_id"])
        if other is None or other["event_id"] != eventId:
            continue
        if log.get("field_index") != match["field_index"]:
            continue
        if log["status"] == "IN_PROGRESS":
            blocking = log
            break
    if blocking is not None:
        raise ApiError(ERR_FIELD_NOT_RESET, 409, "Prior field reset on field %s is not COMPLETE" % match["field_index"])
    for s in slots:
        s["status"] = "ON_FIELD"
        touch(s)
    match["status"] = "ON_FIELD"
    touch(match)
    return success(public(match))


@bp.route("/frc-events/<eventId>/matches/<matchId>/score", methods=["POST"])
def score_match_endpoint(eventId, matchId):
    user_id, _ = require_roles("Scorekeeper")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    gate_posture(event)
    check_from_state(match, "status", "ON_FIELD", TERMINAL["Match"], "Match")
    red = breakdown_for(matchId, "RED")
    blue = breakdown_for(matchId, "BLUE")
    if red is None or blue is None:
        raise ApiError(ERR_SCORE_BREAKDOWN_MISSING, 409, "Both RED and BLUE score breakdowns are required")
    run_score_match(match, final=False)
    if match["series"] == "QUALIFICATION":
        run_ranking_points(match)
    for s in store.queue_slots.values():
        if s["match_id"] == matchId and s["status"] == "ON_FIELD":
            s["status"] = "RELEASED"
            touch(s)
    log = {
        "match_id": matchId,
        "field_index": match["field_index"],
        "started_at": now(),
        "completed_at": None,
        "status": "IN_PROGRESS",
        "actual_seconds": None,
    }
    stamp_new(log)
    store.reset_logs[log["id"]] = log
    match["status"] = "SCORED"
    match["_scored_by"] = user_id
    touch(match)
    return success(public(match))


@bp.route("/frc-events/<eventId>/matches/<matchId>/finalize", methods=["POST"])
def finalize_match(eventId, matchId):
    user_id, _ = require_roles("HeadReferee")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    gate_posture(event)
    check_from_state(match, "status", "SCORED", TERMINAL["Match"], "Match")
    if match.get("_scored_by") is not None and user_id == match["_scored_by"]:
        raise ApiError(ERR_SEGREGATION_VIOLATION, 403, "Scorekeeper cannot finalize their own scores")
    run_score_match(match, final=True)
    match["status"] = "FINALIZED"
    touch(match)
    recompute_match_teams(match)
    return success(public(match))


@bp.route("/frc-events/<eventId>/matches/<matchId>/replay", methods=["POST"])
def replay_match(eventId, matchId):
    require_roles("HeadReferee")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    gate_posture(event)
    check_from_state(match, "status", "SCORED", TERMINAL["Match"], "Match")
    teams = set(match.get("_red_teams", [])) | set(match.get("_blue_teams", []))
    grounds = any(
        v["source_kind"] == "MATCH_REVIEW" and v["team_id"] in teams
        for v in store.violations.values()
    )
    if not grounds:
        raise ApiError(ERR_NO_REPLAY_GROUNDS, 409, "Replay requires a MATCH_REVIEW violation referencing this match")
    match["status"] = "REPLAYED"
    touch(match)
    recompute_match_teams(match)
    return success(public(match))


# ---------------------------------------------------------------------------
# MatchScoreBreakdown
# ---------------------------------------------------------------------------

BREAKDOWN_GET_ROLES = ("EventDirector", "Scorekeeper", "HeadReferee")


@bp.route("/frc-events/<eventId>/matches/<matchId>/score-breakdowns", methods=["POST"])
def create_score_breakdown(eventId, matchId):
    require_roles("Scorekeeper")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    gate_posture(event)
    if match["status"] in TERMINAL["Match"]:
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "Match is already in terminal state %s" % match["status"])
    if match["status"] not in ("SCHEDULED", "QUEUED", "ON_FIELD"):
        raise ApiError(ERR_INVALID_STATE, 409, "Breakdowns cannot be attached once the match is scored")
    body = get_body()
    color = req_enum(body, "alliance_color", {"RED", "BLUE"})
    auto_points = req_int(body, "auto_points", minimum=0)
    teleop_points = req_int(body, "teleop_points", minimum=0)
    endgame_points = req_int(body, "endgame_points", minimum=0)
    foul_points_awarded = req_int(body, "foul_points_awarded", minimum=0)
    tech_foul_count = req_int(body, "tech_foul_count", minimum=0)
    card_issued = req_enum(body, "card_issued", CARD_KINDS)
    if breakdown_for(matchId, color) is not None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "A %s breakdown already exists for this match" % color)
    breakdown = {
        "match_id": matchId,
        "alliance_color": color,
        "auto_points": auto_points,
        "teleop_points": teleop_points,
        "endgame_points": endgame_points,
        "foul_points_awarded": foul_points_awarded,
        "tech_foul_count": tech_foul_count,
        "card_issued": card_issued,
    }
    stamp_new_breakdown(breakdown)
    store.breakdowns[breakdown["id"]] = breakdown
    return success(public(breakdown), code=201)


@bp.route("/frc-events/<eventId>/matches/<matchId>/score-breakdowns", methods=["GET"])
def list_score_breakdowns(eventId, matchId):
    require_roles(*BREAKDOWN_GET_ROLES)
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    items = [b for b in store.breakdowns.values() if b["match_id"] == match["id"]]
    return paginated(items, public)


# ---------------------------------------------------------------------------
# QueueSlot
# ---------------------------------------------------------------------------

SLOT_GET_ROLES = ("EventDirector", "QueueManager", "TeamLead")


@bp.route("/frc-events/<eventId>/matches/<matchId>/queue-slots", methods=["POST"])
def create_queue_slot(eventId, matchId):
    require_roles("QueueManager")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    gate_posture(event)
    body = get_body()
    team_id = req_str(body, "team_id")
    position = req_enum(body, "position", SLOT_POSITIONS)
    team = store.teams.get(team_id)
    if team is None or team["event_id"] != eventId:
        raise ApiError(ERR_TEAM_NOT_FOUND, 404, "Team %s not found" % team_id)
    for s in store.queue_slots.values():
        if s["match_id"] == matchId and s["position"] == position:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Position %s is already taken for this match" % position)
    slot = {
        "match_id": matchId,
        "team_id": team_id,
        "position": position,
        "status": "STAGED",
        "arrived_at": None,
    }
    stamp_new(slot)
    store.queue_slots[slot["id"]] = slot
    return success(public(slot), code=201)


@bp.route("/frc-events/<eventId>/matches/<matchId>/queue-slots", methods=["GET"])
def list_queue_slots(eventId, matchId):
    require_roles(*SLOT_GET_ROLES)
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    items = [s for s in store.queue_slots.values() if s["match_id"] == match["id"]]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/matches/<matchId>/queue-slots/<slotId>", methods=["GET"])
def get_queue_slot(eventId, matchId, slotId):
    require_roles(*SLOT_GET_ROLES)
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    slot = resolve_queue_slot(match, slotId)
    return success(public(slot))


@bp.route("/frc-events/<eventId>/matches/<matchId>/queue-slots/<slotId>/mark-at-field", methods=["POST"])
def mark_slot_at_field(eventId, matchId, slotId):
    require_roles("QueueManager")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    slot = resolve_queue_slot(match, slotId)
    gate_posture(event)
    check_from_state(slot, "status", "STAGED", TERMINAL["QueueSlot"], "QueueSlot")
    if match["status"] != "QUEUED":
        raise ApiError(ERR_MATCH_NOT_QUEUED, 409, "Match must be QUEUED to mark slots at field")
    slot["status"] = "AT_FIELD"
    slot["arrived_at"] = now()
    touch(slot)
    return success(public(slot))


# ---------------------------------------------------------------------------
# FieldResetLog
# ---------------------------------------------------------------------------

RESET_GET_ROLES = ("EventDirector", "FieldResetCrew", "QueueManager")


@bp.route("/frc-events/<eventId>/matches/<matchId>/field-reset-logs", methods=["GET"])
def list_reset_logs(eventId, matchId):
    require_roles(*RESET_GET_ROLES)
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    items = [l for l in store.reset_logs.values() if l["match_id"] == match["id"]]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/matches/<matchId>/field-reset-logs/<logId>", methods=["GET"])
def get_reset_log(eventId, matchId, logId):
    require_roles(*RESET_GET_ROLES)
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    log = resolve_reset_log(match, logId)
    return success(public(log))


@bp.route("/frc-events/<eventId>/matches/<matchId>/field-reset-logs/<logId>/complete", methods=["POST"])
def complete_reset_log(eventId, matchId, logId):
    require_roles("FieldResetCrew")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    log = resolve_reset_log(match, logId)
    gate_posture(event)
    if match["status"] not in ("SCORED", "FINALIZED", "REPLAYED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Reset can only complete while the match is SCORED, FINALIZED or REPLAYED")
    check_from_state(log, "status", "IN_PROGRESS", TERMINAL["FieldResetLog"], "FieldResetLog")
    log["status"] = "COMPLETE"
    log["completed_at"] = now()
    log["actual_seconds"] = int((log["completed_at"] - log["started_at"]).total_seconds())
    touch(log)
    return success(public(log))


@bp.route("/frc-events/<eventId>/matches/<matchId>/field-reset-logs/<logId>/abort", methods=["POST"])
def abort_reset_log(eventId, matchId, logId):
    require_roles("FieldResetCrew")
    event = resolve_event(eventId)
    match = resolve_match(event, matchId)
    log = resolve_reset_log(match, logId)
    gate_posture(event)
    if match["status"] != "CANCELLED":
        raise ApiError(ERR_INVALID_STATE, 409, "Reset can only abort when the match is CANCELLED")
    check_from_state(log, "status", "IN_PROGRESS", TERMINAL["FieldResetLog"], "FieldResetLog")
    log["status"] = "ABORTED"
    touch(log)
    return success(public(log))


# ---------------------------------------------------------------------------
# Projected ranking (forward_looking variant; read-only)
# ---------------------------------------------------------------------------

@bp.route("/frc-events/<eventId>/teams/<teamId>/projected-ranking", methods=["GET"])
def projected_ranking(eventId, teamId):
    require_roles("EventDirector", "TeamLead", "Scorekeeper", "HeadReferee")
    event = resolve_event(eventId)
    team = resolve_team(event, teamId)
    score, tie, n = compute_team_aggregates(team, include_scored=True)
    return success({
        "projected_ranking_score": float(score),
        "projected_ranking_tie_break": float(tie),
        "projected_matches_played": n,
    })
