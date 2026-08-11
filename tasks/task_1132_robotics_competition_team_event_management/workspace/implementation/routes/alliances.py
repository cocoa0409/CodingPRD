"""Alliance, AllianceSelectionRound, and the snake-draft pick endpoint (PRD 3.6)."""
from flask import Blueprint, request

from auth import require_roles
from db import store, stamp_new, touch
from envelope import success, paginated
from errors import (
    ApiError,
    ERR_EVENT_WRONG_STATUS,
    ERR_INVALID_REQUEST,
    ERR_OUT_OF_TURN,
    ERR_PICK_INELIGIBLE,
    ERR_STALE_VERSION,
    ERR_TEAM_NOT_FOUND,
)
from services import (
    current_captain_for,
    is_pick_eligible,
    picks_made_in_round,
    seal_forming_alliances,
    selection_alliances,
)
from util import (
    TERMINAL,
    check_from_state,
    gate_posture,
    get_body,
    public,
    req_int,
    req_str,
    resolve_event,
    resolve_alliance,
    resolve_round,
)

bp = Blueprint("alliances", __name__)

ALLIANCE_GET_ROLES = ("EventDirector", "HeadReferee", "TeamLead", "Scorekeeper")
ROUND_GET_ROLES = ("EventDirector", "TeamLead")


@bp.route("/frc-events/<eventId>/alliances", methods=["POST"])
def create_alliance(eventId):
    require_roles("EventDirector")
    event = resolve_event(eventId)
    gate_posture(event)
    body = get_body()
    seed = req_int(body, "seed", minimum=1)
    captain_team_id = req_str(body, "captain_team_id")
    captain = store.teams.get(captain_team_id)
    if captain is None or captain["event_id"] != eventId:
        raise ApiError(ERR_TEAM_NOT_FOUND, 404, "Team %s not found" % captain_team_id)
    alliance = {
        "event_id": eventId,
        "seed": seed,
        "captain_team_id": captain_team_id,
        "pick1_team_id": None,
        "pick2_team_id": None,
        "status": "FORMING",
    }
    stamp_new(alliance)
    store.alliances[alliance["id"]] = alliance
    return success(public(alliance), code=201)


@bp.route("/frc-events/<eventId>/alliances", methods=["GET"])
def list_alliances(eventId):
    require_roles(*ALLIANCE_GET_ROLES)
    event = resolve_event(eventId)
    items = [a for a in store.alliances.values() if a["event_id"] == event["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/alliances/<allianceId>", methods=["GET"])
def get_alliance(eventId, allianceId):
    require_roles(*ALLIANCE_GET_ROLES)
    event = resolve_event(eventId)
    alliance = resolve_alliance(event, allianceId)
    return success(public(alliance))


@bp.route("/frc-events/<eventId>/alliance-selection-rounds", methods=["GET"])
def list_rounds(eventId):
    require_roles(*ROUND_GET_ROLES)
    event = resolve_event(eventId)
    items = [r for r in store.rounds.values() if r["event_id"] == event["id"]]
    return paginated(items, public)


@bp.route("/frc-events/<eventId>/alliance-selection-rounds/<roundId>", methods=["GET"])
def get_round(eventId, roundId):
    require_roles(*ROUND_GET_ROLES)
    event = resolve_event(eventId)
    rnd = resolve_round(event, roundId)
    return success(public(rnd))


@bp.route("/frc-events/<eventId>/alliance-selection-rounds/<roundId>/pick", methods=["POST"])
def pick(eventId, roundId):
    user_id, _ = require_roles("TeamLead")
    event = resolve_event(eventId)
    rnd = resolve_round(event, roundId)
    body = get_body()
    team_id = req_str(body, "team_id")
    team = store.teams.get(team_id)
    if team is None or team["event_id"] != eventId:
        raise ApiError(ERR_TEAM_NOT_FOUND, 404, "Team %s not found" % team_id)
    if event["status"] != "ALLIANCE_SELECTION":
        raise ApiError(ERR_EVENT_WRONG_STATUS, 409, "Picks are only accepted while ALLIANCE_SELECTION")
    gate_posture(event)
    check_from_state(rnd, "status", "OPEN", TERMINAL["AllianceSelectionRound"], "AllianceSelectionRound")
    # Priority 16: pick eligibility of the target team.
    if not is_pick_eligible(event, team):
        raise ApiError(ERR_PICK_INELIGIBLE, 422, "Team is not eligible to be picked")
    # Priority 17: the acting TeamLead must be the captain whose pick is due.
    acting_person = store.persons.get(user_id)
    acting_team_id = acting_person.get("team_id") if acting_person is not None else None
    current = rnd.get("current_captain_team_id")
    if acting_team_id is None or acting_team_id != current:
        raise ApiError(ERR_OUT_OF_TURN, 409, "It is not this captain's turn to pick")
    # Priority 22: OCC against the round version.
    expected = body.get("expected_round_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, "expected_round_version must be an integer")
        if expected != rnd["version"]:
            raise ApiError(ERR_STALE_VERSION, 412, "expected_round_version does not match current round version")
    # Write the pick onto the acting captain's alliance.
    alliance = None
    for a in selection_alliances(eventId):
        if a.get("captain_team_id") == current and a["status"] == "FORMING":
            alliance = a
            break
    if alliance is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "No FORMING alliance found for the current captain")
    field = "pick1_team_id" if rnd["round_index"] == 1 else "pick2_team_id"
    alliance[field] = team_id
    touch(alliance)
    # Advance the snake order / complete the round.
    total = len(selection_alliances(eventId))
    made = picks_made_in_round(event, rnd["round_index"])
    if made >= total:
        rnd["status"] = "COMPLETE"
        rnd["current_captain_team_id"] = None
        touch(rnd)
        if rnd["round_index"] == 1:
            round2 = {
                "event_id": eventId,
                "round_index": 2,
                "status": "OPEN",
                "current_captain_team_id": current_captain_for(event, 2),
            }
            stamp_new(round2)
            store.rounds[round2["id"]] = round2
        else:
            seal_forming_alliances(event)
    else:
        rnd["current_captain_team_id"] = current_captain_for(event, rnd["round_index"])
        touch(rnd)
    return success(public(rnd))
