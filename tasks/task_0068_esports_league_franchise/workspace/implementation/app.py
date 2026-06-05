import os
from flask import Flask, request

from db import db, new_id, now_iso
from errors import (
    ApiError, err,
    ERR_FORBIDDEN_ROLE, ERR_NOT_TEAM_OWNER, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_TRADE_WINDOW_CLOSED, ERR_TEAM_RESTRICTED,
    ERR_DUPLICATE_RESOURCE, ERR_INVALID_TRADE_ASSETS, ERR_ROSTER_LIMIT_EXCEEDED,
    ERR_PLAYOFF_PRECONDITION, ERR_INVALID_FIELD_VALUE, ERR_CONTRACT_TERM_OVERLAP,
    ERR_STINT_OVERLAP, ERR_VALIDATION,
)
from response import success, success_list, error_response
from middleware import get_auth, require_role
from helpers import (
    get_json_body, require_fields, parse_pagination, paginate,
    sort_by_created, require_int,
)
import serializers as S
import services as svc

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_VALIDATION", str(e), 400)


# ---------------------------------------------------------------------------
# Existence helpers (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def find_season(sid):
    s = db.seasons.get(sid)
    if not s:
        raise err(ERR_NOT_FOUND, "Season not found.")
    return s


def find_team(tid):
    t = db.teams.get(tid)
    if not t:
        raise err(ERR_NOT_FOUND, "Team not found.")
    return t


def find_player(pid):
    p = db.players.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "Player not found.")
    return p


def find_contract(cid):
    c = db.contracts.get(cid)
    if not c:
        raise err(ERR_NOT_FOUND, "Contract not found.")
    return c


def find_trade(tid):
    t = db.trades.get(tid)
    if not t:
        raise err(ERR_NOT_FOUND, "Trade not found.")
    return t


def find_fine(fid):
    f = db.fines.get(fid)
    if not f:
        raise err(ERR_NOT_FOUND, "Fine not found.")
    return f


def find_sponsorship(sid):
    s = db.sponsorships.get(sid)
    if not s:
        raise err(ERR_NOT_FOUND, "Sponsorship not found.")
    return s


def find_stint(sid):
    s = db.stints.get(sid)
    if not s:
        raise err(ERR_NOT_FOUND, "Stint not found.")
    return s


def base_entity(extra):
    e = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    e.update(extra)
    return e


# ===========================================================================
# SEASONS
# ===========================================================================

@app.route("/seasons", methods=["POST"])
def create_season():
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    body = get_json_body()
    require_fields(body, ["name", "salary_cap_cents"])

    name = body["name"]
    if not isinstance(name, str):
        raise err(ERR_INVALID_FIELD_VALUE, "name must be a string.")
    salary_cap = require_int(body, "salary_cap_cents", minimum=1)

    roster_min = body.get("roster_min", 5)
    roster_max = body.get("roster_max", 8)
    two_way_max = body.get("two_way_max", 2)
    penalty_threshold = body.get("penalty_threshold", 3)

    for fld, val, mn in [
        ("roster_min", roster_min, 1),
        ("two_way_max", two_way_max, 0),
        ("penalty_threshold", penalty_threshold, 1),
    ]:
        if not isinstance(val, int) or isinstance(val, bool):
            raise err(ERR_INVALID_FIELD_VALUE, f"{fld} must be an integer.")
        if val < mn:
            raise err(ERR_INVALID_FIELD_VALUE, f"{fld} must be >= {mn}.")
    if not isinstance(roster_max, int) or isinstance(roster_max, bool):
        raise err(ERR_INVALID_FIELD_VALUE, "roster_max must be an integer.")
    if roster_max < roster_min:
        raise err(ERR_INVALID_FIELD_VALUE, "roster_max must be >= roster_min.")

    s = base_entity({
        "name": name,
        "salary_cap_cents": salary_cap,
        "roster_min": roster_min,
        "roster_max": roster_max,
        "two_way_max": two_way_max,
        "penalty_threshold": penalty_threshold,
        "trade_window_state": "CLOSED",
        "phase": "SETUP",
    })
    db.seasons[s["id"]] = s
    return success(S.ser_season(s), 201)


@app.route("/seasons/<sid>", methods=["GET"])
def get_season(sid):
    get_auth()
    s = find_season(sid)
    return success(S.ser_season(s), 200)


@app.route("/seasons/<sid>/start-regular", methods=["POST"])
def start_regular(sid):
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    s = find_season(sid)
    if s["phase"] != "SETUP":
        raise err(ERR_INVALID_STATE, "Season is not in SETUP.")
    s["phase"] = "REGULAR"
    svc.touch(s)
    return success(S.ser_season(s), 200)


@app.route("/seasons/<sid>/trade-window", methods=["POST"])
def trade_window(sid):
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    s = find_season(sid)
    if s["phase"] != "REGULAR":
        raise err(ERR_INVALID_STATE, "Trade window can only be toggled during REGULAR.")
    body = get_json_body()
    require_fields(body, ["trade_window_state"])
    val = body["trade_window_state"]
    if val not in ("OPEN", "CLOSED"):
        raise err(ERR_INVALID_FIELD_VALUE, "trade_window_state must be OPEN or CLOSED.")
    s["trade_window_state"] = val
    svc.touch(s)
    return success(S.ser_season(s), 200)


@app.route("/seasons/<sid>/start-playoffs", methods=["POST"])
def start_playoffs(sid):
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    s = find_season(sid)
    if s["phase"] != "REGULAR":
        raise err(ERR_INVALID_STATE, "Season is not in REGULAR.")
    if s["trade_window_state"] != "CLOSED":
        # window must be closed; precondition for playoffs
        raise err(ERR_PLAYOFF_PRECONDITION, "Trade window must be CLOSED to start playoffs.")
    teams = [t for t in db.teams.values() if t["season_id"] == sid]
    for t in teams:
        if svc.active_standard_count(t["id"]) < s["roster_min"]:
            raise err(ERR_PLAYOFF_PRECONDITION,
                      "Every team must carry at least roster_min ACTIVE STANDARD contracts.")
    # rank: penalty_points asc, payroll_active_cents desc, created_at asc
    ordered = sorted(teams, key=lambda t: (t["penalty_points"],
                                           -t["payroll_active_cents"],
                                           t["created_at"], t["_seq"]))
    for idx, t in enumerate(ordered):
        t["seed"] = idx + 1
        t["eliminated"] = False
        svc.touch(t)
    s["phase"] = "PLAYOFFS"
    svc.touch(s)
    return success(S.ser_season(s), 200)


@app.route("/seasons/<sid>/complete", methods=["POST"])
def complete_season(sid):
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    s = find_season(sid)
    if s["phase"] != "PLAYOFFS":
        raise err(ERR_INVALID_STATE, "Season is not in PLAYOFFS.")
    teams = [t for t in db.teams.values() if t["season_id"] == sid]
    alive = [t for t in teams if t["eliminated"] is False]
    if len(alive) != 1:
        raise err(ERR_PLAYOFF_PRECONDITION, "Exactly one non-eliminated team required to complete.")
    s["phase"] = "COMPLETE"
    svc.touch(s)
    return success(S.ser_season(s), 200)


# ===========================================================================
# TEAMS
# ===========================================================================

@app.route("/teams", methods=["POST"])
def create_team():
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    body = get_json_body()
    require_fields(body, ["season_id", "name", "market_size_weight"])
    season = find_season(body["season_id"])
    name = body["name"]
    if not isinstance(name, str):
        raise err(ERR_INVALID_FIELD_VALUE, "name must be a string.")
    weight = require_int(body, "market_size_weight", minimum=1)
    # uniqueness within season (case-sensitive exact)
    for t in db.teams.values():
        if t["season_id"] == season["id"] and t["name"] == name:
            raise err(ERR_DUPLICATE_RESOURCE, "Team name already exists in this season.")
    t = base_entity({
        "season_id": season["id"],
        "name": name,
        "market_size_weight": weight,
        "payroll_active_cents": 0,
        "penalty_points": 0,
        "posture": "OPEN",
        "seed": None,
        "eliminated": False,
    })
    db.teams[t["id"]] = t
    return success(S.ser_team(t), 201)


@app.route("/teams/<tid>", methods=["GET"])
def get_team(tid):
    get_auth()
    t = find_team(tid)
    return success(S.ser_team(t), 200)


@app.route("/teams", methods=["GET"])
def list_teams():
    get_auth()
    limit, offset = parse_pagination()
    season_id = request.args.get("season_id")
    items = [t for t in db.teams.values()
             if season_id is None or t["season_id"] == season_id]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_team(t) for t in window], limit, offset, total)


@app.route("/teams/<tid>/payroll", methods=["GET"])
def team_payroll(tid):
    get_auth()
    t = find_team(tid)
    season = db.seasons.get(t["season_id"])
    cap = season["salary_cap_cents"] if season else 0
    payroll = svc.compute_payroll_active(tid)
    full = svc.compute_full_commitment(tid)
    tax = svc.luxury_tax_cents(payroll, cap)
    return success({
        "payroll_active_cents": payroll,
        "full_commitment_cents": full,
        "salary_cap_cents": cap,
        "luxury_tax_cents": tax,
    }, 200)


@app.route("/teams/<tid>/contracts", methods=["GET"])
def team_contracts(tid):
    get_auth()
    find_team(tid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [c for c in db.contracts.values()
             if c["team_id"] == tid and (status is None or c["status"] == status)]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_contract(c) for c in window], limit, offset, total)


@app.route("/teams/<tid>/fines", methods=["GET"])
def team_fines(tid):
    get_auth()
    find_team(tid)
    limit, offset = parse_pagination()
    items = [f for f in db.fines.values() if f["team_id"] == tid]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_fine(f) for f in window], limit, offset, total)


@app.route("/teams/<tid>/revenue-shares", methods=["GET"])
def team_revenue_shares(tid):
    get_auth()
    find_team(tid)
    limit, offset = parse_pagination()
    items = [r for r in db.revenue_shares.values() if r["team_id"] == tid]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_revenue_share(r) for r in window], limit, offset, total)


@app.route("/teams/<tid>/eliminate", methods=["POST"])
def eliminate_team(tid):
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    t = find_team(tid)
    t["eliminated"] = True
    svc.touch(t)
    return success(S.ser_team(t), 200)


# ===========================================================================
# PLAYERS
# ===========================================================================

@app.route("/players", methods=["POST"])
def create_player():
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    body = get_json_body()
    require_fields(body, ["season_id", "handle"])
    season = find_season(body["season_id"])
    handle = body["handle"]
    if not isinstance(handle, str):
        raise err(ERR_INVALID_FIELD_VALUE, "handle must be a string.")
    for p in db.players.values():
        if p["season_id"] == season["id"] and p["handle"] == handle:
            raise err(ERR_DUPLICATE_RESOURCE, "Player handle already exists in this season.")
    p = base_entity({
        "season_id": season["id"],
        "handle": handle,
        "status": "FREE_AGENT",
    })
    db.players[p["id"]] = p
    return success(S.ser_player(p), 201)


@app.route("/players/<pid>", methods=["GET"])
def get_player(pid):
    get_auth()
    p = find_player(pid)
    return success(S.ser_player(p), 200)


@app.route("/players", methods=["GET"])
def list_players():
    get_auth()
    limit, offset = parse_pagination()
    season_id = request.args.get("season_id")
    items = [p for p in db.players.values()
             if season_id is None or p["season_id"] == season_id]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_player(p) for p in window], limit, offset, total)


# ===========================================================================
# CONTRACTS
# ===========================================================================

def _player_active_contracts(player_id, exclude_id=None):
    return [c for c in db.contracts.values()
            if c["player_id"] == player_id and c["status"] == "ACTIVE"
            and c["id"] != exclude_id]


def _terms_overlap(a_start, a_end, b_start, b_end):
    # closed intervals; touching endpoints count as overlap
    return a_start <= b_end and b_start <= a_end


@app.route("/contracts", methods=["POST"])
def create_contract():
    role, uid = get_auth()
    require_role(role, ["TeamGM"])
    body = get_json_body()
    require_fields(body, ["team_id", "player_id", "base_salary_cents",
                          "contract_type", "term_start", "term_end"])
    # existence left-to-right: team then player
    team = find_team(body["team_id"])
    player = find_player(body["player_id"])
    # ownership
    if team["id"] != uid:
        raise err(ERR_NOT_TEAM_OWNER, "GM may only sign contracts for their own team.")

    season = db.seasons.get(team["season_id"])

    # duplicate: player already holds an ACTIVE contract
    if player["status"] != "FREE_AGENT" or _player_active_contracts(player["id"]):
        raise err(ERR_DUPLICATE_RESOURCE, "Player already holds an ACTIVE contract.")

    # field-value validity
    salary = require_int(body, "base_salary_cents", minimum=1)
    ctype = body["contract_type"]
    if ctype not in ("STANDARD", "TWO_WAY"):
        raise err(ERR_INVALID_FIELD_VALUE, "contract_type must be STANDARD or TWO_WAY.")
    term_start = body["term_start"]
    term_end = body["term_end"]
    if not isinstance(term_start, str) or not isinstance(term_end, str):
        raise err(ERR_INVALID_FIELD_VALUE, "term_start and term_end must be ISO 8601 strings.")
    if term_end < term_start:
        raise err(ERR_INVALID_FIELD_VALUE, "term_end must be >= term_start.")

    # contract-term overlap (closed interval, touching counts)
    for c in _player_active_contracts(player["id"]):
        if _terms_overlap(term_start, term_end, c["term_start"], c["term_end"]):
            raise err(ERR_CONTRACT_TERM_OVERLAP, "Contract term overlaps an existing ACTIVE contract.")

    # roster limits after add
    if ctype == "STANDARD":
        if svc.active_standard_count(team["id"]) + 1 > season["roster_max"]:
            raise err(ERR_ROSTER_LIMIT_EXCEEDED, "Standard roster limit exceeded.")
    else:  # TWO_WAY unpromoted
        if svc.active_two_way_unpromoted_count(team["id"]) + 1 > season["two_way_max"]:
            raise err(ERR_ROSTER_LIMIT_EXCEEDED, "Two-way roster limit exceeded.")

    c = base_entity({
        "team_id": team["id"],
        "player_id": player["id"],
        "base_salary_cents": salary,
        "contract_type": ctype,
        "term_start": term_start,
        "term_end": term_end,
        "two_way_promoted": False,
        "status": "ACTIVE",
    })
    db.contracts[c["id"]] = c
    player["status"] = "SIGNED"
    svc.recompute_team_payroll(team)
    svc.touch(team)
    return success(S.ser_contract(c), 201)


@app.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    get_auth()
    c = find_contract(cid)
    return success(S.ser_contract(c), 200)


@app.route("/contracts", methods=["GET"])
def list_contracts():
    get_auth()
    limit, offset = parse_pagination()
    team_id = request.args.get("team_id")
    player_id = request.args.get("player_id")
    status = request.args.get("status")
    items = [c for c in db.contracts.values()
             if (team_id is None or c["team_id"] == team_id)
             and (player_id is None or c["player_id"] == player_id)
             and (status is None or c["status"] == status)]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_contract(c) for c in window], limit, offset, total)


@app.route("/contracts/<cid>/promote", methods=["POST"])
def promote_contract(cid):
    role, uid = get_auth()
    require_role(role, ["TeamGM"])
    c = find_contract(cid)
    team = find_team(c["team_id"])
    if team["id"] != uid:
        raise err(ERR_NOT_TEAM_OWNER, "GM may only promote their own team's contracts.")
    # state legality
    if c["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Contract is not ACTIVE.")
    if c["contract_type"] != "TWO_WAY" or c["two_way_promoted"] is True:
        raise err(ERR_INVALID_STATE, "Only an unpromoted TWO_WAY contract can be promoted.")
    # posture gate
    if team["posture"] == "RESTRICTED":
        raise err(ERR_TEAM_RESTRICTED, "Team is RESTRICTED.")
    season = db.seasons.get(team["season_id"])
    # roster limit: treat as standard-counting after promotion
    if svc.active_standard_count(team["id"]) + 1 > season["roster_max"]:
        raise err(ERR_ROSTER_LIMIT_EXCEEDED, "Standard roster limit exceeded after promotion.")
    # expected_team_version carried but NOT an OCC stale check (per PRD §3.3/§2.7)
    c["two_way_promoted"] = True
    svc.touch(c)
    svc.recompute_team_payroll(team)
    svc.touch(team)
    return success(S.ser_contract(c), 200)


@app.route("/contracts/<cid>/waive", methods=["POST"])
def waive_contract(cid):
    role, uid = get_auth()
    require_role(role, ["TeamGM"])
    c = find_contract(cid)
    team = find_team(c["team_id"])
    if team["id"] != uid:
        raise err(ERR_NOT_TEAM_OWNER, "GM may only waive their own team's contracts.")
    if c["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Contract is not ACTIVE.")
    if team["posture"] == "RESTRICTED":
        raise err(ERR_TEAM_RESTRICTED, "Team is RESTRICTED.")
    # expected_team_version carried but NOT an OCC stale check
    c["status"] = "WAIVED"
    svc.touch(c)
    # maybe free the player
    player = db.players.get(c["player_id"])
    if player and not _player_active_contracts(player["id"]):
        player["status"] = "FREE_AGENT"
    svc.recompute_team_payroll(team)
    svc.touch(team)
    return success(S.ser_contract(c), 200)


# ===========================================================================
# STINTS
# ===========================================================================

@app.route("/stints", methods=["POST"])
def create_stint():
    role, uid = get_auth()
    require_role(role, ["TeamGM"])
    body = get_json_body()
    require_fields(body, ["contract_id", "starts_at", "ends_at"])
    c = find_contract(body["contract_id"])
    team = find_team(c["team_id"])
    if team["id"] != uid:
        raise err(ERR_NOT_TEAM_OWNER, "GM may only log stints against their own team's contracts.")
    # contract must be ACTIVE and TWO_WAY
    if c["status"] != "ACTIVE" or c["contract_type"] != "TWO_WAY":
        raise err(ERR_INVALID_STATE, "Stint must target an ACTIVE TWO_WAY contract.")
    starts_at = body["starts_at"]
    ends_at = body["ends_at"]
    if not isinstance(starts_at, str) or not isinstance(ends_at, str):
        raise err(ERR_INVALID_FIELD_VALUE, "starts_at and ends_at must be ISO 8601 strings.")
    if not (ends_at > starts_at):
        raise err(ERR_INVALID_FIELD_VALUE, "ends_at must be strictly greater than starts_at.")
    player_id = c["player_id"]
    # half-open interval overlap; adjacency allowed
    for st in db.stints.values():
        if st["player_id"] != player_id:
            continue
        if starts_at < st["ends_at"] and st["starts_at"] < ends_at:
            raise err(ERR_STINT_OVERLAP, "Stint overlaps an existing stint for this player.")
    st = base_entity({
        "contract_id": c["id"],
        "player_id": player_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    })
    db.stints[st["id"]] = st
    return success(S.ser_stint(st), 201)


@app.route("/stints/<sid>", methods=["GET"])
def get_stint(sid):
    get_auth()
    st = find_stint(sid)
    return success(S.ser_stint(st), 200)


@app.route("/stints", methods=["GET"])
def list_stints():
    get_auth()
    limit, offset = parse_pagination()
    contract_id = request.args.get("contract_id")
    player_id = request.args.get("player_id")
    items = [s for s in db.stints.values()
             if (contract_id is None or s["contract_id"] == contract_id)
             and (player_id is None or s["player_id"] == player_id)]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_stint(s) for s in window], limit, offset, total)


# ===========================================================================
# TRADES
# ===========================================================================

@app.route("/trades", methods=["POST"])
def create_trade():
    role, uid = get_auth()
    require_role(role, ["TeamGM"])
    body = get_json_body()
    require_fields(body, ["season_id", "from_team_id", "to_team_id",
                          "contract_ids_out", "contract_ids_in"])
    season = find_season(body["season_id"])
    from_team = find_team(body["from_team_id"])
    to_team = find_team(body["to_team_id"])
    # ownership: GM owns from_team
    if from_team["id"] != uid:
        raise err(ERR_NOT_TEAM_OWNER, "GM may only propose trades from their own team.")

    cout = body["contract_ids_out"]
    cin = body["contract_ids_in"]
    if not isinstance(cout, list) or not isinstance(cin, list):
        raise err(ERR_VALIDATION, "contract_ids_out and contract_ids_in must be arrays.")

    # trade window must be OPEN
    if season["trade_window_state"] != "OPEN":
        raise err(ERR_TRADE_WINDOW_CLOSED, "Trade window is CLOSED.")

    # asset validation: existence + membership + not both empty
    if len(cout) == 0 and len(cin) == 0:
        raise err(ERR_INVALID_TRADE_ASSETS, "Both contract lists are empty.")
    for cid in cout:
        c = db.contracts.get(cid)
        if not c or c["status"] != "ACTIVE" or c["team_id"] != from_team["id"]:
            raise err(ERR_INVALID_TRADE_ASSETS, "contract_ids_out must be ACTIVE contracts on from_team.")
    for cid in cin:
        c = db.contracts.get(cid)
        if not c or c["status"] != "ACTIVE" or c["team_id"] != to_team["id"]:
            raise err(ERR_INVALID_TRADE_ASSETS, "contract_ids_in must be ACTIVE contracts on to_team.")

    t = base_entity({
        "season_id": season["id"],
        "from_team_id": from_team["id"],
        "to_team_id": to_team["id"],
        "contract_ids_out": list(cout),
        "contract_ids_in": list(cin),
        "status": "PROPOSED",
    })
    db.trades[t["id"]] = t
    return success(S.ser_trade(t), 201)


@app.route("/trades/<tid>", methods=["GET"])
def get_trade(tid):
    get_auth()
    t = find_trade(tid)
    return success(S.ser_trade(t), 200)


@app.route("/trades", methods=["GET"])
def list_trades():
    get_auth()
    limit, offset = parse_pagination()
    season_id = request.args.get("season_id")
    from_team_id = request.args.get("from_team_id")
    to_team_id = request.args.get("to_team_id")
    status = request.args.get("status")
    items = [t for t in db.trades.values()
             if (season_id is None or t["season_id"] == season_id)
             and (from_team_id is None or t["from_team_id"] == from_team_id)
             and (to_team_id is None or t["to_team_id"] == to_team_id)
             and (status is None or t["status"] == status)]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_trade(t) for t in window], limit, offset, total)


@app.route("/trades/<tid>/accept", methods=["POST"])
def accept_trade(tid):
    role, uid = get_auth()
    require_role(role, ["TeamGM"])
    t = find_trade(tid)
    from_team = find_team(t["from_team_id"])
    to_team = find_team(t["to_team_id"])
    season = db.seasons.get(t["season_id"])
    # ownership: GM owns to_team
    if to_team["id"] != uid:
        raise err(ERR_NOT_TEAM_OWNER, "Only the to_team GM may accept.")
    # state legality
    if t["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Trade is not PROPOSED.")
    # OCC: expected_to_team_version
    body = get_json_body()
    require_fields(body, ["expected_to_team_version"])
    expected = body["expected_to_team_version"]
    if expected != to_team["version"]:
        raise err(ERR_STALE_VERSION, "to_team version is stale.")
    # trade window
    if season["trade_window_state"] != "OPEN":
        raise err(ERR_TRADE_WINDOW_CLOSED, "Trade window is CLOSED.")
    # posture gate
    if from_team["posture"] == "RESTRICTED" or to_team["posture"] == "RESTRICTED":
        raise err(ERR_TEAM_RESTRICTED, "An involved team is RESTRICTED.")
    # asset revalidation
    cout = t["contract_ids_out"]
    cin = t["contract_ids_in"]
    for cid in cout:
        c = db.contracts.get(cid)
        if not c or c["status"] != "ACTIVE" or c["team_id"] != from_team["id"]:
            raise err(ERR_INVALID_TRADE_ASSETS, "An outgoing contract is no longer valid.")
    for cid in cin:
        c = db.contracts.get(cid)
        if not c or c["status"] != "ACTIVE" or c["team_id"] != to_team["id"]:
            raise err(ERR_INVALID_TRADE_ASSETS, "An incoming contract is no longer valid.")

    # roster limits post-swap: simulate counts
    def post_counts(team_id, gained, lost):
        std = svc.active_standard_count(team_id)
        tw = svc.active_two_way_unpromoted_count(team_id)
        for cid in lost:
            c = db.contracts[cid]
            if svc.cap_counts(c):
                std -= 1
            elif c["contract_type"] == "TWO_WAY" and not c["two_way_promoted"]:
                tw -= 1
        for cid in gained:
            c = db.contracts[cid]
            if svc.cap_counts(c):
                std += 1
            elif c["contract_type"] == "TWO_WAY" and not c["two_way_promoted"]:
                tw += 1
        return std, tw

    from_std, from_tw = post_counts(from_team["id"], cin, cout)
    to_std, to_tw = post_counts(to_team["id"], cout, cin)
    if (from_std > season["roster_max"] or to_std > season["roster_max"]
            or from_tw > season["two_way_max"] or to_tw > season["two_way_max"]):
        raise err(ERR_ROSTER_LIMIT_EXCEEDED, "Post-trade roster limit exceeded.")

    # commit cascade
    for cid in cout:
        c = db.contracts[cid]
        c["team_id"] = to_team["id"]
        svc.touch(c)
    for cid in cin:
        c = db.contracts[cid]
        c["team_id"] = from_team["id"]
        svc.touch(c)
    svc.recompute_team_payroll(from_team)
    svc.recompute_team_payroll(to_team)
    svc.touch(from_team)
    svc.touch(to_team)
    t["status"] = "ACCEPTED"
    svc.touch(t)
    return success(S.ser_trade(t), 200)


@app.route("/trades/<tid>/reject", methods=["POST"])
def reject_trade(tid):
    role, uid = get_auth()
    require_role(role, ["TeamGM"])
    t = find_trade(tid)
    to_team = find_team(t["to_team_id"])
    if to_team["id"] != uid:
        raise err(ERR_NOT_TEAM_OWNER, "Only the to_team GM may reject.")
    if t["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Trade is not PROPOSED.")
    t["status"] = "REJECTED"
    svc.touch(t)
    return success(S.ser_trade(t), 200)


@app.route("/trades/<tid>/withdraw", methods=["POST"])
def withdraw_trade(tid):
    role, uid = get_auth()
    require_role(role, ["TeamGM"])
    t = find_trade(tid)
    from_team = find_team(t["from_team_id"])
    if from_team["id"] != uid:
        raise err(ERR_NOT_TEAM_OWNER, "Only the from_team GM may withdraw.")
    if t["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, "Trade is not PROPOSED.")
    t["status"] = "WITHDRAWN"
    svc.touch(t)
    return success(S.ser_trade(t), 200)


# ===========================================================================
# FINES
# ===========================================================================

@app.route("/fines", methods=["POST"])
def create_fine():
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    body = get_json_body()
    require_fields(body, ["team_id", "player_id", "amount_cents", "penalty_points"])
    team = find_team(body["team_id"])
    player = find_player(body["player_id"])
    amount = require_int(body, "amount_cents", minimum=1)
    points = require_int(body, "penalty_points", minimum=1)
    # attributed player must be SIGNED to a contract on team_id
    signed_here = any(c["player_id"] == player["id"] and c["team_id"] == team["id"]
                      and c["status"] == "ACTIVE" for c in db.contracts.values())
    if not signed_here:
        raise err(ERR_INVALID_FIELD_VALUE, "Player must be SIGNED to a contract on this team.")
    f = base_entity({
        "team_id": team["id"],
        "player_id": player["id"],
        "amount_cents": amount,
        "penalty_points": points,
        "status": "ASSESSED",
    })
    db.fines[f["id"]] = f
    season = db.seasons.get(team["season_id"])
    team["penalty_points"] += points
    if team["posture"] == "OPEN" and team["penalty_points"] >= season["penalty_threshold"]:
        team["posture"] = "RESTRICTED"
    svc.touch(team)
    return success(S.ser_fine(f), 201)


@app.route("/fines/<fid>", methods=["GET"])
def get_fine(fid):
    get_auth()
    f = find_fine(fid)
    return success(S.ser_fine(f), 200)


@app.route("/fines", methods=["GET"])
def list_fines():
    get_auth()
    limit, offset = parse_pagination()
    team_id = request.args.get("team_id")
    player_id = request.args.get("player_id")
    items = [f for f in db.fines.values()
             if (team_id is None or f["team_id"] == team_id)
             and (player_id is None or f["player_id"] == player_id)]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_fine(f) for f in window], limit, offset, total)


@app.route("/fines/<fid>/waive", methods=["POST"])
def waive_fine(fid):
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    f = find_fine(fid)
    if f["status"] != "ASSESSED":
        raise err(ERR_INVALID_STATE, "Fine is not ASSESSED.")
    f["status"] = "WAIVED"
    svc.touch(f)
    team = db.teams.get(f["team_id"])
    if team:
        season = db.seasons.get(team["season_id"])
        team["penalty_points"] -= f["penalty_points"]
        if team["posture"] == "RESTRICTED" and team["penalty_points"] < season["penalty_threshold"]:
            team["posture"] = "OPEN"
        svc.touch(team)
    return success(S.ser_fine(f), 200)


# ===========================================================================
# SPONSORSHIPS
# ===========================================================================

@app.route("/sponsorships", methods=["POST"])
def create_sponsorship():
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    body = get_json_body()
    require_fields(body, ["season_id", "sponsor_name", "pool_cents"])
    season = find_season(body["season_id"])
    sponsor_name = body["sponsor_name"]
    if not isinstance(sponsor_name, str):
        raise err(ERR_INVALID_FIELD_VALUE, "sponsor_name must be a string.")
    pool = require_int(body, "pool_cents", minimum=1)
    league_share = body.get("league_share_pct", 0.40)
    if isinstance(league_share, bool) or not isinstance(league_share, (int, float)):
        raise err(ERR_INVALID_FIELD_VALUE, "league_share_pct must be a number.")
    if not (league_share >= 0 and league_share < 1):
        raise err(ERR_INVALID_FIELD_VALUE, "league_share_pct must be in [0, 1).")
    s = base_entity({
        "season_id": season["id"],
        "sponsor_name": sponsor_name,
        "pool_cents": pool,
        "league_share_pct": league_share,
        "status": "PENDING",
    })
    db.sponsorships[s["id"]] = s
    return success(S.ser_sponsorship(s), 201)


@app.route("/sponsorships/<sid>", methods=["GET"])
def get_sponsorship(sid):
    get_auth()
    s = find_sponsorship(sid)
    return success(S.ser_sponsorship(s), 200)


@app.route("/sponsorships", methods=["GET"])
def list_sponsorships():
    get_auth()
    limit, offset = parse_pagination()
    season_id = request.args.get("season_id")
    items = [s for s in db.sponsorships.values()
             if season_id is None or s["season_id"] == season_id]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_sponsorship(s) for s in window], limit, offset, total)


@app.route("/sponsorships/<sid>/revenue-shares", methods=["GET"])
def sponsorship_revenue_shares(sid):
    get_auth()
    find_sponsorship(sid)
    limit, offset = parse_pagination()
    items = [r for r in db.revenue_shares.values() if r["sponsorship_id"] == sid]
    items = sort_by_created(items)
    window, total = paginate(items, limit, offset)
    return success_list([S.ser_revenue_share(r) for r in window], limit, offset, total)


@app.route("/sponsorships/<sid>/distribute", methods=["POST"])
def distribute_sponsorship(sid):
    role, uid = get_auth()
    require_role(role, ["LeagueCommissioner"])
    s = find_sponsorship(sid)
    # state legality
    if s["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Sponsorship is not PENDING.")
    # OCC
    body = get_json_body()
    require_fields(body, ["expected_sponsorship_version"])
    expected = body["expected_sponsorship_version"]
    if expected != s["version"]:
        raise err(ERR_STALE_VERSION, "Sponsorship version is stale.")
    teams = [t for t in db.teams.values() if t["season_id"] == s["season_id"]]
    if len(teams) < 1:
        raise err(ERR_INVALID_STATE, "Season has no teams to distribute to.")
    allocations = svc.revenue_waterfall(s["pool_cents"], s["league_share_pct"], teams)
    for team, amount, weight in allocations:
        r = {
            "id": new_id(),
            "created_at": now_iso(),
            "_seq": db.next_seq(),
            "sponsorship_id": s["id"],
            "team_id": team["id"],
            "amount_cents": amount,
            "weight_used": weight,
        }
        db.revenue_shares[r["id"]] = r
    s["status"] = "DISTRIBUTED"
    svc.touch(s)
    return success(S.ser_sponsorship(s), 200)


# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
