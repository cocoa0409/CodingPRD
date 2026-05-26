"""DraftPick endpoints."""
from flask import Blueprint, g, request

from db import store
from errors import (
    ERR_AUCTION_BID_INVALID,
    ERR_FAAB_INSUFFICIENT,
    ERR_ROSTER_OVER_CAP,
    APIError,
    err_forbidden,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import require_role
from response import success_array, success_object
from services.common import (
    bump,
    get_draft_pick,
    get_league,
    get_player,
    get_team,
    new_common_fields,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)
from services.roster import get_non_ir_count

bp = Blueprint("draft_picks", __name__)


# ---------------- POST /draft-picks ----------------

@bp.route("/draft-picks", methods=["POST"])
def create_draft_pick():
    require_role("Commissioner", "TeamOwner")
    body = request.get_json(silent=True) or {}
    league_id = body.get("league_id")
    team_id = body.get("team_id")
    player_id = body.get("player_id")
    if not isinstance(league_id, str):
        raise err_invalid_request("league_id required.")
    if not isinstance(team_id, str):
        raise err_invalid_request("team_id required.")
    if not isinstance(player_id, str):
        raise err_invalid_request("player_id required.")
    # TeamOwner ownership check (priority 2 — before existence).
    if g.user_role == "TeamOwner" and g.user_id != team_id:
        raise err_forbidden("TeamOwner may only submit picks for their own team.")

    # Body-FK existence checks (priority 4).
    league = get_league(league_id)
    team = get_team(team_id)
    player = get_player(player_id)
    if team["league_id"] != league_id:
        raise err_not_found("Team not in this league.")

    if league["status"] != "DRAFTING":
        raise err_invalid_state("League not in DRAFTING.")

    round_ = body.get("round")
    if not isinstance(round_, int) or isinstance(round_, bool) or round_ < 1 or round_ > 20:
        raise err_invalid_request("round must be int 1..20.")
    overall_pick = body.get("overall_pick")
    if not isinstance(overall_pick, int) or isinstance(overall_pick, bool) or overall_pick < 1:
        raise err_invalid_request("overall_pick must be int >= 1.")
    cost_cents = body.get("cost_cents")
    if not isinstance(cost_cents, int) or isinstance(cost_cents, bool):
        raise err_invalid_request("cost_cents required (int).")
    keeper_round = body.get("keeper_round")
    if keeper_round is not None:
        if not isinstance(keeper_round, int) or isinstance(keeper_round, bool):
            raise err_invalid_request("keeper_round must be int or null.")
        if keeper_round < 1 or keeper_round > 20:
            raise err_invalid_request("keeper_round out of range.")
    is_keeper = bool(body.get("is_keeper", False))

    # Monotonic overall_pick across this league.
    league_picks = [dp for dp in store().draft_picks.values() if dp["league_id"] == league_id]
    if league_picks:
        max_overall = max(int(dp["overall_pick"]) for dp in league_picks)
        if overall_pick <= max_overall:
            raise err_invalid_request("overall_pick must be monotonic.")

    # Roster-cap check: would this push the team over roster_size?
    # (We use the count of existing draft picks for the team — equivalent
    # since each pick will become a non-IR slot at finalize.)
    team_picks_count = sum(
        1 for dp in store().draft_picks.values()
        if dp["league_id"] == league_id and dp["team_id"] == team_id
    )
    if (team_picks_count + 1) > int(league["roster_size"]):
        raise APIError(ERR_ROSTER_OVER_CAP, 422, "Team's draft picks exceed roster_size.")

    # FAAB / cost validation (per draft_type).
    if league["draft_type"] == "SNAKE":
        if cost_cents != 0:
            raise APIError(ERR_AUCTION_BID_INVALID, 422,
                           "SNAKE cost_cents must be 0.")
    else:  # AUCTION
        if cost_cents < 0:
            raise APIError(ERR_AUCTION_BID_INVALID, 422, "cost_cents < 0.")
        remaining_slots = int(league["roster_size"]) - (team_picks_count + 1)
        reserve = remaining_slots * 100  # $1 = 100 cents per remaining slot
        max_allowed = int(team["faab_balance_cents"]) - reserve
        if cost_cents > max_allowed:
            raise APIError(ERR_AUCTION_BID_INVALID, 422,
                           "cost_cents exceeds remaining FAAB minus reserves.")

    s = store()
    common = new_common_fields(s.next_seq())
    pick = {
        **common,
        "league_id": league_id,
        "team_id": team_id,
        "player_id": player_id,
        "round": round_,
        "overall_pick": overall_pick,
        "cost_cents": cost_cents,
        "keeper_round": keeper_round,
        "is_keeper": is_keeper,
    }
    s.draft_picks[pick["id"]] = pick

    # AUCTION side effect: debit team FAAB.
    if league["draft_type"] == "AUCTION" and cost_cents > 0:
        team["faab_balance_cents"] = int(team["faab_balance_cents"]) - cost_cents
        bump(team)
    else:
        bump(team)
    bump(league)
    return success_object(serialize(pick), code=201)


# ---------------- GET /draft-picks/{id} ----------------

@bp.route("/draft-picks/<dpid>", methods=["GET"])
def get_draft_pick_endpoint(dpid):
    require_role("Commissioner", "TeamOwner")
    return success_object(serialize(get_draft_pick(dpid)))


# ---------------- GET /draft-picks ----------------

@bp.route("/draft-picks", methods=["GET"])
def list_draft_picks():
    require_role("Commissioner", "TeamOwner")
    limit, offset = parse_pagination()
    items = list(store().draft_picks.values())
    league_id = request.args.get("league_id")
    team_id = request.args.get("team_id")
    player_id = request.args.get("player_id")
    if league_id is not None:
        items = [dp for dp in items if dp["league_id"] == league_id]
    if team_id is not None:
        items = [dp for dp in items if dp["team_id"] == team_id]
    if player_id is not None:
        items = [dp for dp in items if dp["player_id"] == player_id]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)
