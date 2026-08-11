"""FrcEvent lifecycle, BuildSeasonMilestone, logical clock endpoints."""
from flask import Blueprint, request

from auth import require_roles
from db import store, stamp_new, touch, now, iso
from envelope import success, paginated
from errors import (
    ApiError,
    ERR_AWARDS_PENDING,
    ERR_EVENT_WRONG_STATUS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MATCHES_OPEN,
    ERR_MILESTONE_MISSING,
    ERR_MILESTONE_NOT_PASSED,
    ERR_SELECTION_INCOMPLETE,
    ERR_STALE_VERSION,
    ERR_TOO_FEW_TEAMS,
)
from services import (
    eligible_match_teams,
    generate_match_schedule,
    recompute_posture,
    recompute_counts,
    run_championship_qualification,
    run_screening_expiry,
    seed_alliance_captains,
    milestones_of_event,
    matches_of_event,
    selection_alliances,
    current_captain_for,
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
    resolve_milestone,
)

bp = Blueprint("events", __name__)

EVENT_STATUSES = {
    "SETUP", "REGISTRATION_OPEN", "REGISTRATION_LOCKED", "BUILD_SEASON",
    "INSPECTION", "MATCHES_RUNNING", "ALLIANCE_SELECTION", "AWARDS", "CLOSED",
}
MILESTONE_KINDS = {"KICKOFF", "STOP_BUILD", "BAG_DAY", "SHIP_DATE", "UNBAG_WINDOW"}
ALL_GET_ROLES = (
    "EventDirector", "RegistrationOfficer", "ScreeningOfficer", "TeamLead",
    "JudgeAdvisor", "Scorekeeper", "QueueManager", "HeadReferee", "Inspector",
    "LeadInspector", "FieldResetCrew", "TravelOfficer", "ProcurementOfficer", "Judge",
)


def _event_status_gate(event, expected):
    if event["status"] != expected:
        raise ApiError(
            ERR_EVENT_WRONG_STATUS, 409,
            "Event status %s does not permit this operation (expected %s)" % (event["status"], expected),
        )


def _check_event_occ(body, event):
    expected = body.get("expected_event_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "expected_event_version must be an integer")
        if expected != event["version"]:
            raise ApiError(ERR_STALE_VERSION, 412, "expected_event_version does not match current event version")


# ---------------------------------------------------------------------------
# FrcEvent CRUD + lifecycle
# ---------------------------------------------------------------------------

@bp.route("/frc-events", methods=["POST"])
def create_event():
    require_roles("EventDirector")
    body = get_body()
    event_code = req_str(body, "event_code")
    event_name = req_str(body, "event_name")
    season_year = req_int(body, "season_year")
    start_date = req_dt(body, "start_date")
    end_date = req_dt(body, "end_date")
    team_capacity = req_int(body, "team_capacity")
    match_cycle_minutes = req_int(body, "match_cycle_minutes", minimum=4)
    field_count = req_int(body, "field_count", minimum=1)
    championship_slots = req_int(body, "championship_slots")

    for e in store.events.values():
        if e["event_code"] == event_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "event_code must be unique across all events")

    event = {
        "event_code": event_code,
        "event_name": event_name,
        "season_year": season_year,
        "start_date": start_date,
        "end_date": end_date,
        "status": "SETUP",
        "posture": "OPEN",
        "team_capacity": team_capacity,
        "match_cycle_minutes": match_cycle_minutes,
        "field_count": field_count,
        "championship_slots": championship_slots,
        "registered_team_count": 0,
        "cleared_mentor_count": 0,
        "outstanding_violation_count": 0,
    }
    # Optional per-event build-season budget cap (not declared in the endpoint
    # input list; enforced by part-order approve only when provided).
    if "budget_cap_cents" in body and body.get("budget_cap_cents") is not None:
        cap = body.get("budget_cap_cents")
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "budget_cap_cents must be a non-negative integer")
        event["budget_cap_cents"] = cap
    stamp_new(event)
    store.events[event["id"]] = event
    return success(public(event), code=201)


@bp.route("/frc-events", methods=["GET"])
def list_events():
    require_roles(*ALL_GET_ROLES)
    items = list(store.events.values())
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    season_year = request.args.get("season_year")
    if season_year is not None:
        try:
            sy = int(season_year)
        except ValueError:
            raise ApiError(ERR_INVALID_REQUEST, 400, "season_year must be an integer")
        items = [e for e in items if e["season_year"] == sy]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>", methods=["GET"])
def get_event(eventId):
    require_roles(*ALL_GET_ROLES)
    event = resolve_event(eventId)
    return success(public(event))


@bp.route("/frc-events/<eventId>/open-registration", methods=["POST"])
def open_registration(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    _event_status_gate(event, "SETUP")
    gate_posture(event)
    kickoff = [m for m in milestones_of_event(eventId) if m["kind"] == "KICKOFF" and m["status"] == "SCHEDULED"]
    if not kickoff:
        raise ApiError(ERR_MILESTONE_MISSING, 409, "A SCHEDULED KICKOFF milestone is required to open registration")
    if not (event["team_capacity"] > 0):
        raise ApiError(ERR_INVALID_REQUEST, 400, "team_capacity must be greater than zero to open registration")
    event["status"] = "REGISTRATION_OPEN"
    recompute_posture(event, bump=False)
    touch(event)
    return success(public(event))


@bp.route("/frc-events/<eventId>/lock-registration", methods=["POST"])
def lock_registration(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    _event_status_gate(event, "REGISTRATION_OPEN")
    gate_posture(event, require_open=True)
    for t in store.teams.values():
        if t["event_id"] == eventId and t["registration_status"] in ("PENDING_PAYMENT", "PAYMENT_CLEARED"):
            t["registration_status"] = "WITHDRAWN"
            touch(t)
    event["status"] = "REGISTRATION_LOCKED"
    recompute_counts(event)
    touch(event)
    return success(public(event))


@bp.route("/frc-events/<eventId>/open-build-season", methods=["POST"])
def open_build_season(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    _event_status_gate(event, "REGISTRATION_LOCKED")
    gate_posture(event, require_open=True)
    recompute_counts(event)
    if event["registered_team_count"] < 2:
        raise ApiError(ERR_TOO_FEW_TEAMS, 409, "At least 2 confirmed teams are required to open build season")
    for m in milestones_of_event(eventId):
        if m["kind"] == "KICKOFF" and m["status"] == "SCHEDULED":
            m["status"] = "ARMED"
            touch(m)
    event["status"] = "BUILD_SEASON"
    touch(event)
    return success(public(event))


@bp.route("/frc-events/<eventId>/open-inspection", methods=["POST"])
def open_inspection(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    _event_status_gate(event, "BUILD_SEASON")
    gate_posture(event)
    stop_build = [m for m in milestones_of_event(eventId) if m["kind"] == "STOP_BUILD"]
    if not stop_build or not any(m["status"] == "PASSED" for m in stop_build):
        raise ApiError(ERR_MILESTONE_NOT_PASSED, 409, "STOP_BUILD milestone is not in PASSED state")
    event["status"] = "INSPECTION"
    touch(event)
    return success(public(event))


@bp.route("/frc-events/<eventId>/start-matches", methods=["POST"])
def start_matches(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    body = get_body()
    _event_status_gate(event, "INSPECTION")
    gate_posture(event, require_open=True)
    for t in store.teams.values():
        if t["event_id"] == eventId and t["registration_status"] == "CONFIRMED":
            if t["robot_inspection_status"] not in ("PASSED", "WAIVED"):
                raise ApiError(
                    ERR_INSPECTION_INCOMPLETE, 409,
                    "Every CONFIRMED team must have robot_inspection_status PASSED or WAIVED",
                )
    critical_open = len([
        v for v in store.violations.values()
        if v["severity"] == "CRITICAL" and v["resolution_status"] != "RESOLVED"
        and store.teams.get(v["team_id"]) is not None
        and store.teams[v["team_id"]]["event_id"] == eventId
    ])
    if critical_open > 0:
        raise ApiError(ERR_EVENT_FROZEN, 409, "Unresolved CRITICAL violations block start-matches")
    # Validate team-count floor before any write so a failed call commits nothing.
    if len(eligible_match_teams(event)) < 6:
        raise ApiError(ERR_TOO_FEW_TEAMS, 409, "Fewer than 6 eligible teams for match generation")
    _check_event_occ(body, event)
    generate_match_schedule(event)
    event["status"] = "MATCHES_RUNNING"
    touch(event)
    return success(public(event))


@bp.route("/frc-events/<eventId>/open-alliance-selection", methods=["POST"])
def open_alliance_selection(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    _event_status_gate(event, "MATCHES_RUNNING")
    gate_posture(event)
    open_matches = [
        m for m in matches_of_event(eventId)
        if m["series"] == "QUALIFICATION" and m["status"] not in ("FINALIZED", "REPLAYED")
    ]
    if open_matches:
        raise ApiError(ERR_MATCHES_OPEN, 409, "QUALIFICATION matches remain non-final")
    # Precondition (captain seeding) checked before any write for atomicity.
    captains = seed_alliance_captains(event)
    round1 = {
        "event_id": eventId,
        "round_index": 1,
        "status": "OPEN",
        "current_captain_team_id": current_captain_for(event, 1),
    }
    stamp_new(round1)
    store.rounds[round1["id"]] = round1
    event["status"] = "ALLIANCE_SELECTION"
    touch(event)
    return success(public(event))


@bp.route("/frc-events/<eventId>/close-alliance-selection", methods=["POST"])
def close_alliance_selection(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    _event_status_gate(event, "ALLIANCE_SELECTION")
    gate_posture(event)
    rounds = [r for r in store.rounds.values() if r["event_id"] == eventId]
    r1 = [r for r in rounds if r["round_index"] == 1]
    r2 = [r for r in rounds if r["round_index"] == 2]
    if not r1 or not r2 or r1[0]["status"] != "COMPLETE" or r2[0]["status"] != "COMPLETE":
        raise ApiError(ERR_SELECTION_INCOMPLETE, 409, "Selection rounds 1 and 2 must both be COMPLETE")
    open_playoffs = [
        m for m in matches_of_event(eventId)
        if m["series"] == "PLAYOFF" and m["status"] not in ("FINALIZED", "REPLAYED")
    ]
    if open_playoffs:
        raise ApiError(ERR_MATCHES_OPEN, 409, "PLAYOFF matches remain non-final")
    event["status"] = "AWARDS"
    touch(event)
    return success(public(event))


@bp.route("/frc-events/<eventId>/close-event", methods=["POST"])
def close_event(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    _event_status_gate(event, "AWARDS")
    gate_posture(event)
    pending_awards = [
        a for a in store.awards.values()
        if a["event_id"] == eventId and a["status"] != "PRESENTED"
    ]
    if pending_awards:
        raise ApiError(ERR_AWARDS_PENDING, 409, "All awards must be PRESENTED before closing the event")
    recompute_counts(event)
    if event["outstanding_violation_count"] != 0:
        raise ApiError(ERR_INVALID_STATE, 409, "Outstanding violations remain; cannot close the event")
    run_championship_qualification(event)
    event["status"] = "CLOSED"
    touch(event)
    return success(public(event))


# ---------------------------------------------------------------------------
# BuildSeasonMilestone
# ---------------------------------------------------------------------------

MILESTONE_ROLES = ("EventDirector", "RegistrationOfficer", "TeamLead", "ProcurementOfficer")


@bp.route("/frc-events/<eventId>/milestones", methods=["POST"])
def create_milestone(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    gate_posture(event)
    body = get_body()
    kind = req_enum(body, "kind", MILESTONE_KINDS)
    scheduled_at = req_dt(body, "scheduled_at")
    window = body.get("window_minutes", 0)
    if not isinstance(window, int) or isinstance(window, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "window_minutes must be an integer")
    if kind == "UNBAG_WINDOW":
        if not (window > 0):
            raise ApiError(ERR_INVALID_REQUEST, 400, "window_minutes must be > 0 for UNBAG_WINDOW")
    else:
        if window != 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "window_minutes must be 0 for point-in-time milestones")
    milestone = {
        "event_id": eventId,
        "kind": kind,
        "scheduled_at": scheduled_at,
        "window_minutes": window,
        "status": "SCHEDULED",
    }
    stamp_new(milestone)
    store.milestones[milestone["id"]] = milestone
    return success(public(milestone), code=201)


@bp.route("/frc-events/<eventId>/milestones", methods=["GET"])
def list_milestones(eventId):
    require_roles(*MILESTONE_ROLES)
    event = resolve_event(eventId)
    items = [m for m in store.milestones.values() if m["event_id"] == event["id"]]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/milestones/<milestoneId>", methods=["GET"])
def get_milestone(eventId, milestoneId):
    require_roles(*MILESTONE_ROLES)
    event = resolve_event(eventId)
    milestone = resolve_milestone(event, milestoneId)
    return success(public(milestone))


@bp.route("/frc-events/<eventId>/milestones/<milestoneId>/mark-passed", methods=["POST"])
def mark_milestone_passed(eventId, milestoneId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    gate_posture(event)
    milestone = resolve_milestone(event, milestoneId)
    check_from_state(milestone, "status", {"SCHEDULED", "ARMED"}, TERMINAL["BuildSeasonMilestone"], "Milestone")
    milestone["status"] = "PASSED"
    touch(milestone)
    return success(public(milestone))


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.9) — test-driving endpoint
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("EventDirector")
    body = get_body()
    target = req_dt(body, "to_iso8601")
    store.clock = target
    run_screening_expiry()
    for event in store.events.values():
        recompute_posture(event)
    return success({"current_utc": iso(now())})
