"""Trade endpoints + VetoVote."""
from flask import Blueprint, g, request

from db import now_iso, store
from errors import (
    ERR_FAAB_INSUFFICIENT,
    ERR_TRADE_LOCKED_DURING_GAME,
    ERR_TRADE_PLAYER_NOT_ON_ROSTER,
    ERR_VETO_SELF_INTEREST,
    APIError,
    err_cross_state,
    err_forbidden,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import require_role
from response import success_array, success_object
from services.calculations import trade_fairness
from services.common import (
    bump,
    check_trade_finalize_occ,
    get_league,
    get_player,
    get_team,
    get_trade,
    get_veto_vote,
    new_common_fields,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)
from services.common import check_occ
from services.roster import (
    create_roster_slot,
    delete_roster_slots_for,
    find_player_slot,
)

bp = Blueprint("trades", __name__)


def _check_trade_player_rosters(trade, proposing_team_id, target_team_id):
    """ERR_TRADE_PLAYER_NOT_ON_ROSTER if any offered/requested player not
    currently on the right team's roster.
    """
    for pid in trade["players_offered"]:
        player = store().players.get(pid)
        if player is None or player.get("current_team_id") != proposing_team_id:
            raise APIError(ERR_TRADE_PLAYER_NOT_ON_ROSTER, 422,
                           f"Offered player {pid} not on proposing team.")
    for pid in trade["players_requested"]:
        player = store().players.get(pid)
        if player is None or player.get("current_team_id") != target_team_id:
            raise APIError(ERR_TRADE_PLAYER_NOT_ON_ROSTER, 422,
                           f"Requested player {pid} not on target team.")


# ---------------- POST /trades ----------------

@bp.route("/trades", methods=["POST"])
def create_trade():
    require_role("TeamOwner")
    body = request.get_json(silent=True) or {}
    league_id = body.get("league_id")
    proposing_team_id = body.get("proposing_team_id")
    target_team_id = body.get("target_team_id")
    players_offered = body.get("players_offered")
    players_requested = body.get("players_requested")
    faab_offered_cents = body.get("faab_offered_cents", 0)
    if not isinstance(league_id, str):
        raise err_invalid_request("league_id required.")
    if not isinstance(proposing_team_id, str):
        raise err_invalid_request("proposing_team_id required.")
    if not isinstance(target_team_id, str):
        raise err_invalid_request("target_team_id required.")
    if not isinstance(players_offered, list) or not (1 <= len(players_offered) <= 5):
        raise err_invalid_request("players_offered must be a 1..5 array.")
    if not isinstance(players_requested, list) or not (1 <= len(players_requested) <= 5):
        raise err_invalid_request("players_requested must be a 1..5 array.")
    if not isinstance(faab_offered_cents, int) or isinstance(faab_offered_cents, bool) or faab_offered_cents < 0:
        raise err_invalid_request("faab_offered_cents must be non-negative int.")
    if proposing_team_id == target_team_id:
        raise err_invalid_request("proposing_team_id == target_team_id.")

    # TeamOwner identity match (ownership; priority 2 — before existence).
    if g.user_id != proposing_team_id:
        raise err_forbidden("Only the proposing team owner may propose a trade.")

    # Body-FK existence (priority 4).
    league = get_league(league_id)
    proposing_team = get_team(proposing_team_id)
    target_team = get_team(target_team_id)
    if proposing_team["league_id"] != league_id or target_team["league_id"] != league_id:
        raise err_not_found("Team not in this league.")
    for pid in list(players_offered) + list(players_requested):
        if not isinstance(pid, str) or pid not in store().players:
            raise err_not_found(f"Player {pid} not found.")

    # Cross-entity state: league must be IN_SEASON.
    if league["status"] != "IN_SEASON":
        raise err_cross_state("League not IN_SEASON.")

    # Trade player roster check.
    _check_trade_player_rosters(
        {"players_offered": players_offered, "players_requested": players_requested},
        proposing_team_id, target_team_id,
    )
    # FAAB check.
    if faab_offered_cents > int(proposing_team["faab_balance_cents"]):
        raise APIError(ERR_FAAB_INSUFFICIENT, 422,
                       "faab_offered_cents > proposing team's balance.")

    s = store()
    common = new_common_fields(s.next_seq())
    trade = {
        **common,
        "league_id": league_id,
        "proposing_team_id": proposing_team_id,
        "target_team_id": target_team_id,
        "players_offered": list(players_offered),
        "players_requested": list(players_requested),
        "faab_offered_cents": faab_offered_cents,
        "state": "PROPOSED",
        "veto_votes_count": 0,
        "accepted_at": None,
    }
    s.trades[trade["id"]] = trade
    return success_object(serialize(trade), code=201)


# ---------------- GET /trades/{id} ----------------

@bp.route("/trades/<tid>", methods=["GET"])
def get_trade_endpoint(tid):
    require_role("Commissioner", "TeamOwner")
    return success_object(serialize(get_trade(tid)))


# ---------------- GET /trades ----------------

@bp.route("/trades", methods=["GET"])
def list_trades():
    require_role("Commissioner", "TeamOwner")
    limit, offset = parse_pagination()
    items = list(store().trades.values())
    league_id = request.args.get("league_id")
    proposing_team_id = request.args.get("proposing_team_id")
    target_team_id = request.args.get("target_team_id")
    state = request.args.get("state")
    if league_id is not None:
        items = [t for t in items if t["league_id"] == league_id]
    if proposing_team_id is not None:
        items = [t for t in items if t["proposing_team_id"] == proposing_team_id]
    if target_team_id is not None:
        items = [t for t in items if t["target_team_id"] == target_team_id]
    if state is not None:
        items = [t for t in items if t["state"] == state]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)


# ---------------- POST /trades/{id}/accept ----------------

@bp.route("/trades/<tid>/accept", methods=["POST"])
def accept_trade(tid):
    require_role("TeamOwner")
    trade = get_trade(tid)
    body = request.get_json(silent=True) or {}
    if g.user_id != trade["target_team_id"]:
        raise err_forbidden("Only target team owner may accept.")
    # State check.
    if trade["state"] != "PROPOSED":
        raise err_invalid_state("Trade not PROPOSED.")
    # OCC (non-stale variant -> ERR_INVALID_STATE).
    check_occ(trade, "expected_trade_version", body)
    league = get_league(trade["league_id"])
    if league["status"] != "IN_SEASON":
        raise err_cross_state("League not IN_SEASON.")
    _check_trade_player_rosters(trade, trade["proposing_team_id"], trade["target_team_id"])
    proposing_team = get_team(trade["proposing_team_id"])
    if int(trade["faab_offered_cents"]) > int(proposing_team["faab_balance_cents"]):
        raise APIError(ERR_FAAB_INSUFFICIENT, 422,
                       "Proposer no longer has enough FAAB.")
    # Transition: PROPOSED -> ACCEPTED, then auto-PENDING_VETO. Two version bumps.
    trade["state"] = "ACCEPTED"
    trade["accepted_at"] = now_iso()
    bump(trade)
    trade["state"] = "PENDING_VETO"
    trade["veto_votes_count"] = 0
    bump(trade)
    return success_object(serialize(trade))


# ---------------- POST /trades/{id}/reject ----------------

@bp.route("/trades/<tid>/reject", methods=["POST"])
def reject_trade(tid):
    require_role("TeamOwner")
    trade = get_trade(tid)
    body = request.get_json(silent=True) or {}
    if g.user_id != trade["target_team_id"]:
        raise err_forbidden("Only target team owner may reject.")
    if trade["state"] != "PROPOSED":
        raise err_invalid_state("Trade not PROPOSED.")
    check_occ(trade, "expected_trade_version", body)
    trade["state"] = "REJECTED"
    bump(trade)
    return success_object(serialize(trade))


# ---------------- POST /trades/{id}/withdraw ----------------

@bp.route("/trades/<tid>/withdraw", methods=["POST"])
def withdraw_trade(tid):
    require_role("TeamOwner")
    trade = get_trade(tid)
    body = request.get_json(silent=True) or {}
    if g.user_id != trade["proposing_team_id"]:
        raise err_forbidden("Only proposing team owner may withdraw.")
    if trade["state"] != "PROPOSED":
        raise err_invalid_state("Trade not PROPOSED.")
    check_occ(trade, "expected_trade_version", body)
    trade["state"] = "WITHDRAWN"
    bump(trade)
    return success_object(serialize(trade))


# ---------------- POST /trades/{id}/veto-votes ----------------

@bp.route("/trades/<tid>/veto-votes", methods=["POST"])
def cast_veto_vote(tid):
    require_role("TeamOwner")
    trade = get_trade(tid)
    body = request.get_json(silent=True) or {}
    voter_team_id = body.get("voter_team_id")
    vote = body.get("vote")
    if not isinstance(voter_team_id, str):
        raise err_invalid_request("voter_team_id required.")
    if vote not in {"VETO", "ALLOW"}:
        raise err_invalid_request("vote must be VETO or ALLOW.")
    # TeamOwner identity must match the voter_team_id (ownership; priority 2).
    if g.user_id != voter_team_id:
        raise err_forbidden("voter_team_id must match X-User-ID.")
    # Body-FK existence (priority 4).
    if voter_team_id not in store().teams:
        raise err_not_found("voter_team_id not found.")
    if trade["state"] != "PENDING_VETO":
        raise err_invalid_state("Trade not PENDING_VETO.")
    # Segregation of duty.
    if voter_team_id == trade["proposing_team_id"] or voter_team_id == trade["target_team_id"]:
        raise APIError(ERR_VETO_SELF_INTEREST, 422,
                       "Trade participants cannot vote.")
    check_occ(trade, "expected_trade_version", body)

    s = store()
    common = new_common_fields(s.next_seq())
    # VetoVote has common_fields=false in scaffold; we still mint id+created_at
    # but strip updated_at + version from output (PRD §2.4).
    vv = {
        "id": common["id"],
        "created_at": common["created_at"],
        "_seq": common["_seq"],
        "trade_id": tid,
        "voter_team_id": voter_team_id,
        "vote": vote,
    }
    s.veto_votes[vv["id"]] = vv

    # Update Trade.
    league = get_league(trade["league_id"])
    if vote == "VETO":
        trade["veto_votes_count"] = int(trade["veto_votes_count"]) + 1
    # Check threshold (per PRD §3.8: when count after recording >= threshold,
    # auto-transition to VETOED).
    if int(trade["veto_votes_count"]) >= int(league["veto_threshold"]):
        trade["state"] = "VETOED"
    bump(trade)
    return success_object(serialize(vv), code=201)


# ---------------- POST /leagues/{id}/finalize-trade/{trade_id} ----------------

@bp.route("/leagues/<lid>/finalize-trade/<tid>", methods=["POST"])
def finalize_trade(lid, tid):
    require_role("Commissioner")
    # Path resolution left-to-right.
    league = get_league(lid)
    trade = get_trade(tid)
    if trade["league_id"] != lid:
        raise err_not_found("Trade does not belong to this league.")
    body = request.get_json(silent=True) or {}

    # OCC stale-version (PRD §2.5: "before any roster swap is applied"; the
    # dedicated 412 fires whenever the commissioner's view of the trade has
    # been invalidated by a subsequent vote bumping Trade.version).
    check_trade_finalize_occ(trade, body)
    # State check.
    if trade["state"] != "PENDING_VETO":
        raise err_invalid_state("Trade not PENDING_VETO.")
    # Cross-entity state.
    if league["status"] != "IN_SEASON":
        raise err_cross_state("League not IN_SEASON.")
    # Trade-during-game lock.
    for m in store().matchups.values():
        if m["league_id"] == lid and m["state"] == "IN_PROGRESS":
            raise APIError(ERR_TRADE_LOCKED_DURING_GAME, 409,
                           "A matchup is currently IN_PROGRESS.")
    # Veto threshold gate.
    if int(trade["veto_votes_count"]) >= int(league["veto_threshold"]):
        raise err_invalid_state("Trade has been vetoed.")
    # Roster + FAAB checks.
    _check_trade_player_rosters(trade, trade["proposing_team_id"], trade["target_team_id"])
    proposing_team = get_team(trade["proposing_team_id"])
    target_team = get_team(trade["target_team_id"])
    if int(trade["faab_offered_cents"]) > int(proposing_team["faab_balance_cents"]):
        raise APIError(ERR_FAAB_INSUFFICIENT, 422,
                       "Proposer FAAB insufficient.")

    # Apply swap.
    # Players offered -> target.
    for pid in trade["players_offered"]:
        player = store().players[pid]
        delete_roster_slots_for(trade["proposing_team_id"], pid)
        player["current_team_id"] = trade["target_team_id"]
        create_roster_slot(
            team_id=trade["target_team_id"], player_id=pid, slot_type="BENCH"
        )
        bump(player)
    # Players requested -> proposing.
    for pid in trade["players_requested"]:
        player = store().players[pid]
        delete_roster_slots_for(trade["target_team_id"], pid)
        player["current_team_id"] = trade["proposing_team_id"]
        create_roster_slot(
            team_id=trade["proposing_team_id"], player_id=pid, slot_type="BENCH"
        )
        bump(player)
    # FAAB transfer.
    if int(trade["faab_offered_cents"]) > 0:
        amt = int(trade["faab_offered_cents"])
        proposing_team["faab_balance_cents"] = int(proposing_team["faab_balance_cents"]) - amt
        target_team["faab_balance_cents"] = int(target_team["faab_balance_cents"]) + amt
    bump(proposing_team)
    bump(target_team)
    trade["state"] = "EXECUTED"
    bump(trade)
    return success_object(serialize(trade))


# ---------------- GET /trades/{id}/fairness ----------------

@bp.route("/trades/<tid>/fairness", methods=["GET"])
def trade_fairness_endpoint(tid):
    require_role("Commissioner", "TeamOwner")
    trade = get_trade(tid)
    payload = trade_fairness(trade)
    return success_object(payload)


# ---------------- GET /trades/{trade_id}/veto-votes (reverse-reach) ----------------

@bp.route("/trades/<tid>/veto-votes", methods=["GET"])
def list_trade_veto_votes(tid):
    require_role("Commissioner", "TeamOwner")
    get_trade(tid)
    limit, offset = parse_pagination()
    items = [v for v in store().veto_votes.values() if v["trade_id"] == tid]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)


# ---------------- GET /veto-votes/{id} ----------------

@bp.route("/veto-votes/<vid>", methods=["GET"])
def get_veto_vote_endpoint(vid):
    require_role("Commissioner", "TeamOwner")
    return success_object(serialize(get_veto_vote(vid)))


# ---------------- GET /veto-votes ----------------

@bp.route("/veto-votes", methods=["GET"])
def list_veto_votes():
    require_role("Commissioner", "TeamOwner")
    limit, offset = parse_pagination()
    items = list(store().veto_votes.values())
    trade_id = request.args.get("trade_id")
    voter_team_id = request.args.get("voter_team_id")
    if trade_id is not None:
        items = [v for v in items if v["trade_id"] == trade_id]
    if voter_team_id is not None:
        items = [v for v in items if v["voter_team_id"] == voter_team_id]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)
