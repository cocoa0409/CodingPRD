"""PlayoffMatchup endpoints."""
import math

from flask import Blueprint, request

from db import store
from errors import (
    ERR_INVALID_STARTER_PLAYER,
    APIError,
    err_cross_state,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import require_role
from response import success_array, success_object
from services.calculations import injury_replacement_projection_for_team
from services.common import (
    bump,
    check_matchup_occ,
    get_league,
    get_matchup,
    get_team,
    new_common_fields,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)
from services.roster import get_roster_slots_for_team

bp = Blueprint("matchups", __name__)


# ---------------- POST /leagues/{id}/matchups ----------------

@bp.route("/leagues/<lid>/matchups", methods=["POST"])
def create_matchup(lid):
    require_role("Commissioner")
    league = get_league(lid)
    body = request.get_json(silent=True) or {}
    week = body.get("week")
    matchup_type = body.get("matchup_type")
    round_ = body.get("round", 0)
    home_team_id = body.get("home_team_id")
    away_team_id = body.get("away_team_id")

    if not isinstance(week, int) or isinstance(week, bool) or week < 1 or week > 17:
        raise err_invalid_request("week must be int 1..17.")
    if matchup_type not in {"REGULAR", "PLAYOFF"}:
        raise err_invalid_request("matchup_type must be REGULAR or PLAYOFF.")
    if not isinstance(round_, int) or isinstance(round_, bool) or round_ < 0 or round_ > 3:
        raise err_invalid_request("round must be int 0..3.")
    if not isinstance(home_team_id, str):
        raise err_invalid_request("home_team_id required.")
    if not isinstance(away_team_id, str):
        raise err_invalid_request("away_team_id required.")
    if home_team_id == away_team_id:
        raise err_invalid_request("home_team_id == away_team_id.")
    home_team = get_team(home_team_id)
    away_team = get_team(away_team_id)
    if home_team["league_id"] != lid or away_team["league_id"] != lid:
        raise err_not_found("Team not in this league.")

    s = store()
    common = new_common_fields(s.next_seq())
    m = {
        **common,
        "league_id": lid,
        "week": week,
        "matchup_type": matchup_type,
        "round": round_,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "home_score": 0,
        "away_score": 0,
        "state": "SCHEDULED",
        "winner_team_id": None,
    }
    s.matchups[m["id"]] = m
    return success_object(serialize(m), code=201)


# ---------------- GET /matchups/{id} ----------------

@bp.route("/matchups/<mid>", methods=["GET"])
def get_matchup_endpoint(mid):
    require_role("Commissioner", "TeamOwner")
    return success_object(serialize(get_matchup(mid)))


# ---------------- GET /matchups ----------------

@bp.route("/matchups", methods=["GET"])
def list_matchups():
    require_role("Commissioner", "TeamOwner")
    limit, offset = parse_pagination()
    items = list(store().matchups.values())
    league_id = request.args.get("league_id")
    week = request.args.get("week")
    matchup_type = request.args.get("matchup_type")
    state = request.args.get("state")
    home_team_id = request.args.get("home_team_id")
    away_team_id = request.args.get("away_team_id")
    winner_team_id = request.args.get("winner_team_id")
    if league_id is not None:
        items = [m for m in items if m["league_id"] == league_id]
    if week is not None:
        try:
            wk = int(week)
            items = [m for m in items if int(m["week"]) == wk]
        except ValueError:
            raise err_invalid_request("week must be int.")
    if matchup_type is not None:
        items = [m for m in items if m["matchup_type"] == matchup_type]
    if state is not None:
        items = [m for m in items if m["state"] == state]
    if home_team_id is not None:
        items = [m for m in items if m["home_team_id"] == home_team_id]
    if away_team_id is not None:
        items = [m for m in items if m["away_team_id"] == away_team_id]
    if winner_team_id is not None:
        items = [m for m in items if m.get("winner_team_id") == winner_team_id]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)


# ---------------- POST /matchups/{id}/start ----------------

@bp.route("/matchups/<mid>/start", methods=["POST"])
def start_matchup(mid):
    require_role("Commissioner")
    m = get_matchup(mid)
    body = request.get_json(silent=True) or {}
    league = get_league(m["league_id"])
    if m["state"] != "SCHEDULED":
        raise err_invalid_state("Matchup not SCHEDULED.")
    check_matchup_occ(m, body)
    if int(league["current_week"]) != int(m["week"]):
        raise err_cross_state("League.current_week != matchup.week.")
    if m["matchup_type"] == "PLAYOFF":
        home_team = get_team(m["home_team_id"])
        away_team = get_team(m["away_team_id"])
        if int(home_team.get("playoff_seed", 0)) <= 0 or int(away_team.get("playoff_seed", 0)) <= 0:
            raise err_cross_state("Both teams must have playoff_seed > 0.")

    # Safety: starters must not be IR_PLACED.
    for team_id in (m["home_team_id"], m["away_team_id"]):
        for slot in get_roster_slots_for_team(team_id):
            if slot["slot_type"] == "STARTER":
                player = store().players.get(slot["player_id"])
                if player is not None and player["status"] == "IR_PLACED":
                    raise APIError(ERR_INVALID_STARTER_PLAYER, 422,
                                   "STARTER cannot be IR_PLACED.")

    # Lock STARTER slots.
    current_week = int(league["current_week"])
    for team_id in (m["home_team_id"], m["away_team_id"]):
        for slot in get_roster_slots_for_team(team_id):
            if slot["slot_type"] == "STARTER":
                slot["week_locked"] = current_week
                bump(slot)
    m["state"] = "IN_PROGRESS"
    bump(m)
    return success_object(serialize(m))


# ---------------- POST /matchups/{id}/finalize ----------------

@bp.route("/matchups/<mid>/finalize", methods=["POST"])
def finalize_matchup(mid):
    require_role("Commissioner")
    m = get_matchup(mid)
    body = request.get_json(silent=True) or {}
    if m["state"] != "IN_PROGRESS":
        raise err_invalid_state("Matchup not IN_PROGRESS.")
    check_matchup_occ(m, body)
    league = get_league(m["league_id"])

    # Decide scores: supplied OR computed.
    home_supplied = body.get("home_score")
    away_supplied = body.get("away_score")

    def _validate_score(v, name):
        if isinstance(v, bool):
            raise err_invalid_request(f"{name} invalid.")
        if not isinstance(v, (int, float)):
            raise err_invalid_request(f"{name} must be numeric.")
        from services.calculations import round_half_up
        return round_half_up(float(v), 2)

    if home_supplied is not None:
        home_score = _validate_score(home_supplied, "home_score")
    else:
        home_score = injury_replacement_projection_for_team(m["home_team_id"], int(m["week"]))
    if away_supplied is not None:
        away_score = _validate_score(away_supplied, "away_score")
    else:
        away_score = injury_replacement_projection_for_team(m["away_team_id"], int(m["week"]))

    # Capture pre-match standings before mutation for tiebreak.
    home_team = get_team(m["home_team_id"])
    away_team = get_team(m["away_team_id"])
    pre_home_pf = float(home_team["total_points_for"])
    pre_away_pf = float(away_team["total_points_for"])

    # Resolve winner.
    if home_score > away_score:
        winner_id = m["home_team_id"]
        loser_id = m["away_team_id"]
    elif away_score > home_score:
        winner_id = m["away_team_id"]
        loser_id = m["home_team_id"]
    else:
        # Tiebreak: higher pre-match total_points_for.
        if pre_home_pf >= pre_away_pf:
            winner_id = m["home_team_id"]
            loser_id = m["away_team_id"]
        else:
            winner_id = m["away_team_id"]
            loser_id = m["home_team_id"]

    m["home_score"] = home_score
    m["away_score"] = away_score
    m["winner_team_id"] = winner_id
    m["state"] = "COMPLETED"
    bump(m)

    # Cascade standings if REGULAR.
    if m["matchup_type"] == "REGULAR":
        winner = store().teams[winner_id]
        loser = store().teams[loser_id]
        # Increment wins/losses.
        winner["wins"] = int(winner["wins"]) + 1
        loser["losses"] = int(loser["losses"]) + 1
        # Aggregate points.
        if winner_id == m["home_team_id"]:
            winner_score, loser_score = home_score, away_score
        else:
            winner_score, loser_score = away_score, home_score
        winner["total_points_for"] = float(winner["total_points_for"]) + winner_score
        winner["total_points_against"] = float(winner["total_points_against"]) + loser_score
        loser["total_points_for"] = float(loser["total_points_for"]) + loser_score
        loser["total_points_against"] = float(loser["total_points_against"]) + winner_score
        # Intra-division win.
        if winner["division"] == loser["division"]:
            winner["intra_division_wins"] = int(winner["intra_division_wins"]) + 1
        bump(winner)
        bump(loser)

    # Cascade bracket advancement if PLAYOFF and round < final_round.
    elif m["matchup_type"] == "PLAYOFF":
        final_round = int(math.log2(league["playoff_team_count"]))
        if int(m["round"]) < final_round:
            _maybe_create_next_round(league, m, winner_id)

    return success_object(serialize(m))


def _maybe_create_next_round(league, m, winner_id):
    """Auto-create next-round matchup pairing this winner against parallel
    bracket's winner if both bracket positions have completed.
    """
    current_round = int(m["round"])
    next_round = current_round + 1
    week = int(m["week"]) + 1

    # Find sibling matchup at the same round, pair with the parallel one.
    # We pair the bracket by seed order: the seed of one team in this matchup
    # vs the seed of the team in the "parallel" position.
    # Simpler approach: gather all completed matchups at current_round for
    # this league; pair them in seed-order: pos i pairs with pos (count - 1 - i).
    league_id = league["id"]
    siblings = [
        mm for mm in store().matchups.values()
        if mm["league_id"] == league_id
        and mm["matchup_type"] == "PLAYOFF"
        and int(mm["round"]) == current_round
    ]
    # Sort siblings by created_at ASC for deterministic pairing.
    siblings.sort(key=lambda x: (x["created_at"], x.get("_seq", 0)))
    n = len(siblings)
    # Find index of `m` within siblings.
    idx = next((i for i, mm in enumerate(siblings) if mm["id"] == m["id"]), None)
    if idx is None:
        return
    # The "parallel" sibling for next-round pairing is the one at position
    # (n - 1 - idx).
    parallel_idx = n - 1 - idx
    if parallel_idx == idx:
        return  # odd count, no parallel
    parallel = siblings[parallel_idx]
    if parallel["state"] != "COMPLETED":
        return  # parallel not done yet — wait for it

    # Determine higher-seed-winner as home: compare seeds of the two winners.
    p_winner_id = parallel.get("winner_team_id")
    if p_winner_id is None:
        return
    # Avoid duplicate creation: check if a next-round matchup involving these
    # two winners already exists.
    for mm in store().matchups.values():
        if (
            mm["league_id"] == league_id
            and mm["matchup_type"] == "PLAYOFF"
            and int(mm["round"]) == next_round
            and {mm["home_team_id"], mm["away_team_id"]} == {winner_id, p_winner_id}
        ):
            return

    # Use the same idx-based pair-up: the lower-idx position's winner is home.
    if idx < parallel_idx:
        home_id, away_id = winner_id, p_winner_id
    else:
        home_id, away_id = p_winner_id, winner_id

    common = new_common_fields(store().next_seq())
    new_m = {
        **common,
        "league_id": league_id,
        "week": week,
        "matchup_type": "PLAYOFF",
        "round": next_round,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_score": 0,
        "away_score": 0,
        "state": "SCHEDULED",
        "winner_team_id": None,
    }
    store().matchups[new_m["id"]] = new_m
