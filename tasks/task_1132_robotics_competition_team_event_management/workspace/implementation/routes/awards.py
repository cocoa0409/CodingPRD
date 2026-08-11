"""Award and InterviewSlot workflows (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles
from db import store, stamp_new, touch, now
from envelope import success, paginated
from errors import (
    ApiError,
    ERR_EVENT_WRONG_STATUS,
    ERR_INTERVIEW_REQUIRED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_JUDGE_DOUBLE_BOOKED,
    ERR_NO_ELIGIBLE_TEAMS,
    ERR_PERSON_NOT_FOUND,
    ERR_TEAM_NOT_FOUND,
    ERR_UNAUTHORIZED_ROLE,
)
from services import select_award_winner
from util import (
    TERMINAL,
    check_from_state,
    gate_posture,
    get_body,
    public,
    req_bool,
    req_dt,
    req_enum,
    req_int,
    req_str,
    resolve_event,
    resolve_award,
    resolve_interview_slot,
)

bp = Blueprint("awards", __name__)

AWARD_GET_ROLES = ("EventDirector", "JudgeAdvisor", "Judge", "TeamLead")
AWARD_KINDS = {
    "CHAIRMANS", "ENGINEERING_INSPIRATION", "ROOKIE_ALL_STAR", "WOODIE_FLOWERS",
    "DEANS_LIST", "SAFETY", "CREATIVITY", "QUALITY", "INNOVATION",
    "GRACIOUS_PROFESSIONALISM",
}


# ---------------------------------------------------------------------------
# Award
# ---------------------------------------------------------------------------

@bp.route("/frc-events/<eventId>/awards", methods=["POST"])
def create_award(eventId):
    require_roles("JudgeAdvisor")
    event = resolve_event(eventId)
    gate_posture(event)
    body = get_body()
    award_kind = req_enum(body, "award_kind", AWARD_KINDS)
    requires_interview = req_bool(body, "requires_interview")
    award = {
        "event_id": eventId,
        "award_kind": award_kind,
        "winner_team_id": None,
        "status": "OPEN",
        "requires_interview": requires_interview,
    }
    stamp_new(award)
    store.awards[award["id"]] = award
    return success(public(award), code=201)


@bp.route("/frc-events/<eventId>/awards", methods=["GET"])
def list_awards(eventId):
    require_roles(*AWARD_GET_ROLES)
    event = resolve_event(eventId)
    items = [a for a in store.awards.values() if a["event_id"] == event["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/awards/<awardId>", methods=["GET"])
def get_award(eventId, awardId):
    require_roles(*AWARD_GET_ROLES)
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    return success(public(award))


@bp.route("/frc-events/<eventId>/awards/<awardId>/begin-judging", methods=["POST"])
def begin_judging(eventId, awardId):
    require_roles("JudgeAdvisor")
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    if event["status"] not in ("MATCHES_RUNNING", "ALLIANCE_SELECTION", "AWARDS"):
        raise ApiError(ERR_EVENT_WRONG_STATUS, 409, "Judging may begin only during MATCHES_RUNNING, ALLIANCE_SELECTION or AWARDS")
    gate_posture(event)
    check_from_state(award, "status", "OPEN", TERMINAL["Award"], "Award")
    award["status"] = "JUDGING"
    touch(award)
    return success(public(award))


@bp.route("/frc-events/<eventId>/awards/<awardId>/decide", methods=["POST"])
def decide_award(eventId, awardId):
    require_roles("JudgeAdvisor")
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    gate_posture(event)
    check_from_state(award, "status", "JUDGING", TERMINAL["Award"], "Award")
    if award.get("requires_interview"):
        completed = any(
            s["award_id"] == awardId and s["status"] == "COMPLETED"
            for s in store.interview_slots.values()
        )
        if not completed:
            raise ApiError(ERR_INTERVIEW_REQUIRED, 422, "Award requires at least one COMPLETED interview")
    winner = select_award_winner(event, award)
    if winner is None:
        raise ApiError(ERR_NO_ELIGIBLE_TEAMS, 409, "No eligible teams for this award")
    award["winner_team_id"] = winner["id"]
    award["status"] = "DECIDED"
    touch(award)
    if award["award_kind"] == "CHAIRMANS":
        if winner.get("qualified_for_championship") is not True:
            winner["qualified_for_championship"] = True
            touch(winner)
    return success(public(award))


@bp.route("/frc-events/<eventId>/awards/<awardId>/present", methods=["POST"])
def present_award(eventId, awardId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    if event["status"] != "AWARDS":
        raise ApiError(ERR_EVENT_WRONG_STATUS, 409, "Awards may only be presented while the event is AWARDS")
    gate_posture(event)
    check_from_state(award, "status", "DECIDED", TERMINAL["Award"], "Award")
    award["status"] = "PRESENTED"
    touch(award)
    return success(public(award))


# ---------------------------------------------------------------------------
# InterviewSlot
# ---------------------------------------------------------------------------

@bp.route("/frc-events/<eventId>/awards/<awardId>/interview-slots", methods=["POST"])
def create_interview_slot(eventId, awardId):
    require_roles("JudgeAdvisor")
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    gate_posture(event)
    body = get_body()
    team_id = req_str(body, "team_id")
    judge_id = req_str(body, "judge_id")
    starts_at = req_dt(body, "starts_at")
    duration_minutes = req_int(body, "duration_minutes", minimum=5)
    team = store.teams.get(team_id)
    if team is None or team["event_id"] != eventId:
        raise ApiError(ERR_TEAM_NOT_FOUND, 404, "Team %s not found" % team_id)
    judge = store.persons.get(judge_id)
    if judge is None or judge.get("_event_id") != eventId:
        raise ApiError(ERR_PERSON_NOT_FOUND, 404, "Judge person %s not found" % judge_id)
    if judge.get("role_kind") != "JUDGE":
        raise ApiError(ERR_INVALID_REQUEST, 400, "judge_id must reference a Person with role_kind JUDGE")
    slot = {
        "award_id": awardId,
        "team_id": team_id,
        "judge_id": judge_id,
        "starts_at": starts_at,
        "duration_minutes": duration_minutes,
        "status": "PROPOSED",
        "score": None,
    }
    stamp_new(slot)
    store.interview_slots[slot["id"]] = slot
    return success(public(slot), code=201)


@bp.route("/frc-events/<eventId>/awards/<awardId>/interview-slots", methods=["GET"])
def list_interview_slots(eventId, awardId):
    require_roles(*AWARD_GET_ROLES)
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    items = [s for s in store.interview_slots.values() if s["award_id"] == award["id"]]
    team_id = request.args.get("team_id")
    if team_id is not None:
        items = [s for s in items if s["team_id"] == team_id]
    judge_id = request.args.get("judge_id")
    if judge_id is not None:
        items = [s for s in items if s["judge_id"] == judge_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/awards/<awardId>/interview-slots/<slotId>", methods=["GET"])
def get_interview_slot(eventId, awardId, slotId):
    require_roles(*AWARD_GET_ROLES)
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    slot = resolve_interview_slot(award, slotId)
    return success(public(slot))


@bp.route("/frc-events/<eventId>/awards/<awardId>/interview-slots/<slotId>/confirm", methods=["POST"])
def confirm_interview_slot(eventId, awardId, slotId):
    user_id, _ = require_roles("TeamLead")
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    slot = resolve_interview_slot(award, slotId)
    gate_posture(event)
    # Ownership: the TeamLead's Person.team_id must equal the slot's team.
    acting = store.persons.get(user_id)
    if acting is None or acting.get("team_id") != slot["team_id"]:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403, "Only the interviewed team's lead may confirm this slot")
    check_from_state(slot, "status", "PROPOSED", TERMINAL["InterviewSlot"], "InterviewSlot")
    # Judge double-booking: half-open interval overlap against other CONFIRMED slots.
    new_start = slot["starts_at"]
    new_end = new_start + timedelta(minutes=slot["duration_minutes"])
    for other in store.interview_slots.values():
        if other["id"] == slotId or other["judge_id"] != slot["judge_id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        o_start = other["starts_at"]
        o_end = o_start + timedelta(minutes=other["duration_minutes"])
        if new_start < o_end and o_start < new_end:
            raise ApiError(ERR_JUDGE_DOUBLE_BOOKED, 409, "Judge already has a CONFIRMED slot overlapping this time")
    slot["status"] = "CONFIRMED"
    touch(slot)
    return success(public(slot))


@bp.route("/frc-events/<eventId>/awards/<awardId>/interview-slots/<slotId>/complete", methods=["POST"])
def complete_interview_slot(eventId, awardId, slotId):
    user_id, _ = require_roles("Judge")
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    slot = resolve_interview_slot(award, slotId)
    gate_posture(event)
    if user_id != slot["judge_id"]:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403, "Only the assigned judge may complete this slot")
    judge = store.persons.get(slot["judge_id"])
    if judge is None or judge.get("screening_status") != "CLEARED":
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403, "Judge screening is not CLEARED")
    check_from_state(slot, "status", "CONFIRMED", TERMINAL["InterviewSlot"], "InterviewSlot")
    body = get_body()
    score = req_int(body, "score", minimum=0, maximum=100)
    slot["status"] = "COMPLETED"
    slot["score"] = score
    touch(slot)
    return success(public(slot))


@bp.route("/frc-events/<eventId>/awards/<awardId>/interview-slots/<slotId>/cancel", methods=["POST"])
def cancel_interview_slot(eventId, awardId, slotId):
    require_roles("JudgeAdvisor")
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    slot = resolve_interview_slot(award, slotId)
    gate_posture(event)
    check_from_state(slot, "status", "PROPOSED", TERMINAL["InterviewSlot"], "InterviewSlot")
    slot["status"] = "CANCELLED"
    touch(slot)
    return success(public(slot))


@bp.route("/frc-events/<eventId>/awards/<awardId>/interview-slots/<slotId>/no-show", methods=["POST"])
def no_show_interview_slot(eventId, awardId, slotId):
    user_id, _ = require_roles("Judge")
    event = resolve_event(eventId)
    award = resolve_award(event, awardId)
    slot = resolve_interview_slot(award, slotId)
    gate_posture(event)
    if user_id != slot["judge_id"]:
        raise ApiError(ERR_UNAUTHORIZED_ROLE, 403, "Only the assigned judge may mark this slot no-show")
    check_from_state(slot, "status", "CONFIRMED", TERMINAL["InterviewSlot"], "InterviewSlot")
    deadline = slot["starts_at"] + timedelta(minutes=slot["duration_minutes"])
    if not (now() > deadline):
        raise ApiError(ERR_INVALID_STATE, 409, "No-show window has not yet elapsed")
    slot["status"] = "NO_SHOW"
    touch(slot)
    return success(public(slot))
