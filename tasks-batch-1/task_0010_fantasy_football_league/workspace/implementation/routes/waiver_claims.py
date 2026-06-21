"""WaiverClaim endpoints."""
from flask import Blueprint, g, request

from db import store
from errors import (
    ERR_DROP_PLAYER_NOT_ON_ROSTER,
    ERR_FAAB_INSUFFICIENT,
    ERR_INVALID_WAIVER_WEEK,
    ERR_ROSTER_OVER_CAP,
    APIError,
    err_cross_state,
    err_forbidden,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import require_role
from response import success_array, success_object
from services.common import (
    bump,
    check_waiver_cancel_occ,
    get_league,
    get_player,
    get_team,
    get_waiver_claim,
    new_common_fields,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)
from services.roster import find_player_slot, get_non_ir_count

bp = Blueprint("waiver_claims", __name__)


# ---------------- POST /waiver-claims ----------------

@bp.route("/waiver-claims", methods=["POST"])
def create_waiver_claim():
    require_role("TeamOwner")
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

    # TeamOwner identity must match (ownership; priority 2 — before existence).
    if g.user_id != team_id:
        raise err_forbidden("TeamOwner may only act on their own team.")

    # Body-FK existence (priority 4).
    league = get_league(league_id)
    team = get_team(team_id)
    player = get_player(player_id)
    drop_player_id = body.get("drop_player_id")
    if drop_player_id is not None:
        if not isinstance(drop_player_id, str):
            raise err_invalid_request("drop_player_id must be string or null.")
        if drop_player_id not in store().players:
            raise err_not_found("drop_player_id not found.")
    if team["league_id"] != league_id:
        raise err_not_found("Team not in this league.")

    # Cross-entity state: league must be IN_SEASON; player not RELEASED.
    if league["status"] != "IN_SEASON":
        raise err_cross_state("League not IN_SEASON.")
    if player["status"] == "RELEASED":
        raise err_cross_state("Player is RELEASED.")

    # Drop-player referential check.
    if drop_player_id is not None:
        if find_player_slot(team_id, drop_player_id) is None:
            raise APIError(ERR_DROP_PLAYER_NOT_ON_ROSTER, 422,
                           "drop_player_id not on team's roster.")

    # Temporal: processing_week must equal League.current_week.
    processing_week = body.get("processing_week")
    if not isinstance(processing_week, int) or isinstance(processing_week, bool):
        raise err_invalid_request("processing_week required (int).")
    if processing_week != int(league["current_week"]):
        raise APIError(ERR_INVALID_WAIVER_WEEK, 422,
                       "processing_week != league.current_week.")

    # Roster cap check: after a win the team would have:
    # current non-IR + 1 (added) - (1 if drop on roster else 0) <= roster_size.
    after = get_non_ir_count(team_id) + 1
    if drop_player_id is not None:
        after -= 1
    if after > int(league["roster_size"]):
        raise APIError(ERR_ROSTER_OVER_CAP, 422,
                       "Win would exceed roster_size.")

    # FAAB check.
    bid_cents = body.get("bid_cents")
    if not isinstance(bid_cents, int) or isinstance(bid_cents, bool) or bid_cents < 0:
        raise err_invalid_request("bid_cents required (non-negative int).")
    if bid_cents > int(league["faab_budget_cents"]):
        raise err_invalid_request("bid_cents above faab_budget_cents.")
    if bid_cents > int(team["faab_balance_cents"]):
        raise APIError(ERR_FAAB_INSUFFICIENT, 422,
                       "bid_cents > team.faab_balance_cents.")

    s = store()
    common = new_common_fields(s.next_seq())
    claim = {
        **common,
        "league_id": league_id,
        "team_id": team_id,
        "player_id": player_id,
        "bid_cents": bid_cents,
        "drop_player_id": drop_player_id,
        "state": "SUBMITTED",
        "processing_week": processing_week,
        "priority_at_submission": int(team["waiver_priority"]),
    }
    s.waiver_claims[claim["id"]] = claim
    return success_object(serialize(claim), code=201)


# ---------------- GET /waiver-claims/{id} ----------------

@bp.route("/waiver-claims/<wid>", methods=["GET"])
def get_waiver_claim_endpoint(wid):
    require_role("Commissioner", "TeamOwner")
    return success_object(serialize(get_waiver_claim(wid)))


# ---------------- GET /waiver-claims ----------------

@bp.route("/waiver-claims", methods=["GET"])
def list_waiver_claims():
    require_role("Commissioner", "TeamOwner")
    limit, offset = parse_pagination()
    items = list(store().waiver_claims.values())
    league_id = request.args.get("league_id")
    team_id = request.args.get("team_id")
    player_id = request.args.get("player_id")
    drop_player_id = request.args.get("drop_player_id")
    state = request.args.get("state")
    if league_id is not None:
        items = [c for c in items if c["league_id"] == league_id]
    if team_id is not None:
        items = [c for c in items if c["team_id"] == team_id]
    if player_id is not None:
        items = [c for c in items if c["player_id"] == player_id]
    if drop_player_id is not None:
        items = [c for c in items if c.get("drop_player_id") == drop_player_id]
    if state is not None:
        items = [c for c in items if c["state"] == state]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)


# ---------------- POST /waiver-claims/{id}/cancel ----------------

@bp.route("/waiver-claims/<wid>/cancel", methods=["POST"])
def cancel_waiver_claim(wid):
    require_role("TeamOwner")
    claim = get_waiver_claim(wid)
    body = request.get_json(silent=True) or {}

    # TeamOwner identity check.
    if g.user_id != claim["team_id"]:
        raise err_forbidden("TeamOwner may only act on their own claims.")
    # State check first: PRD §1.4 priority 5 (ERR_INVALID_STATE) is checked
    # before OCC mismatch (412). But the OCC spec is dedicated and stale —
    # so we check OCC first per §2.5 explicit guard.
    check_waiver_cancel_occ(claim, body)
    if claim["state"] != "SUBMITTED":
        raise err_invalid_state("Claim not SUBMITTED.")
    claim["state"] = "CANCELLED"
    bump(claim)
    return success_object(serialize(claim))
