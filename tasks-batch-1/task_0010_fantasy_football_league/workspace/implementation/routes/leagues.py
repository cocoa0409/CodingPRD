"""League CRUD + lifecycle endpoints."""
import math

from flask import Blueprint, g, request

from db import store
from errors import (
    err_cross_state,
    err_invalid_request,
    err_invalid_state,
)
from middleware import require_role
from response import success_array, success_object
from services.calculations import (
    compute_playoff_seeds,
    draft_pick_value,
    recompute_keeper_costs,
    resolve_waiver_batch,
)
from services.common import (
    bump,
    check_league_occ,
    get_league,
    get_player,
    new_common_fields,
    paginate,
    parse_pagination,
    serialize,
    serialize_list,
    sort_by_created_at,
)
from services.roster import create_roster_slot

bp = Blueprint("leagues", __name__)


# ---------------- helpers ----------------

ALLOWED_DRAFT_TYPES = {"SNAKE", "AUCTION"}
ALLOWED_TIEBREAK_RULES = {"STANDARD", "DIVISION_FIRST"}
ALLOWED_PLAYOFF_TEAM_COUNTS = {2, 4, 8}


def _validate_int(body, name, *, minv=None, maxv=None, required=True):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid_request(f"Missing {name}.")
        return None
    v = body[name]
    if not isinstance(v, int) or isinstance(v, bool):
        raise err_invalid_request(f"{name} must be an integer.")
    if minv is not None and v < minv:
        raise err_invalid_request(f"{name} below minimum.")
    if maxv is not None and v > maxv:
        raise err_invalid_request(f"{name} above maximum.")
    return v


def _validate_str(body, name, *, minlen=1, maxlen=None, required=True):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid_request(f"Missing {name}.")
        return None
    v = body[name]
    if not isinstance(v, str):
        raise err_invalid_request(f"{name} must be a string.")
    stripped = v.strip()
    if minlen is not None and len(stripped) < minlen:
        raise err_invalid_request(f"{name} too short.")
    if maxlen is not None and len(v) > maxlen:
        raise err_invalid_request(f"{name} too long.")
    return v


def _validate_enum(body, name, allowed: set, *, required=True):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid_request(f"Missing {name}.")
        return None
    v = body[name]
    if v not in allowed:
        raise err_invalid_request(f"{name} not in {sorted(allowed)}.")
    return v


def _round_count(playoff_team_count: int) -> int:
    """Bracket rounds implied by playoff_team_count."""
    return int(math.log2(playoff_team_count))


def _team_count_in_league(league_id: str) -> int:
    return sum(1 for t in store().teams.values() if t["league_id"] == league_id)


# ---------------- POST /leagues ----------------

@bp.route("/leagues", methods=["POST"])
def create_league():
    require_role("Commissioner")
    body = request.get_json(silent=True) or {}

    name = _validate_str(body, "name", minlen=1, maxlen=80)
    if not name.strip():
        raise err_invalid_request("name cannot be blank.")
    draft_type = _validate_enum(body, "draft_type", ALLOWED_DRAFT_TYPES)
    roster_size = _validate_int(body, "roster_size", minv=2, maxv=20)
    starter_slot_count = _validate_int(body, "starter_slot_count", minv=1, maxv=11)
    if starter_slot_count > roster_size:
        raise err_invalid_request("starter_slot_count > roster_size.")
    ir_slot_count = _validate_int(body, "ir_slot_count", minv=0, maxv=3)
    faab_budget_cents = _validate_int(body, "faab_budget_cents", minv=0, maxv=1_000_000)
    veto_threshold = _validate_int(body, "veto_threshold", minv=1)
    keeper_limit = _validate_int(body, "keeper_limit", minv=0, maxv=6)
    playoff_team_count = _validate_int(body, "playoff_team_count")
    if playoff_team_count not in ALLOWED_PLAYOFF_TEAM_COUNTS:
        raise err_invalid_request("playoff_team_count must be in {2,4,8}.")
    tiebreak_rule = _validate_enum(body, "tiebreak_rule", ALLOWED_TIEBREAK_RULES)

    s = store()
    common = new_common_fields(s.next_seq())
    league = {
        **common,
        "name": name.strip(),
        "draft_type": draft_type,
        "roster_size": roster_size,
        "starter_slot_count": starter_slot_count,
        "ir_slot_count": ir_slot_count,
        "faab_budget_cents": faab_budget_cents,
        "veto_threshold": veto_threshold,
        "keeper_limit": keeper_limit,
        "playoff_team_count": playoff_team_count,
        "tiebreak_rule": tiebreak_rule,
        "status": "SETUP",
        "current_week": 0,
        "total_faab_pool_cents": 0,
    }
    s.leagues[league["id"]] = league
    return success_object(serialize(league), code=201)


# ---------------- GET /leagues/{id} ----------------

@bp.route("/leagues/<lid>", methods=["GET"])
def get_league_endpoint(lid):
    require_role("Commissioner", "TeamOwner")
    league = get_league(lid)
    return success_object(serialize(league))


# ---------------- GET /leagues ----------------

@bp.route("/leagues", methods=["GET"])
def list_leagues():
    require_role("Commissioner", "TeamOwner")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = list(store().leagues.values())
    if status_filter is not None:
        items = [l for l in items if l["status"] == status_filter]
    items = sort_by_created_at(items)
    sliced, total = paginate(items, limit, offset)
    return success_array(serialize_list(sliced), limit, offset, total)


# ---------------- POST /leagues/{id}/start-draft ----------------

@bp.route("/leagues/<lid>/start-draft", methods=["POST"])
def start_draft(lid):
    require_role("Commissioner")
    league = get_league(lid)
    body = request.get_json(silent=True) or {}
    if league["status"] != "SETUP":
        raise err_invalid_state("League not in SETUP.")
    check_league_occ(league, body)

    teams = [t for t in store().teams.values() if t["league_id"] == lid]
    team_count = len(teams)
    if team_count < 2:
        raise err_invalid_state("Need at least 2 teams.")
    if league["playoff_team_count"] > team_count:
        raise err_invalid_state("playoff_team_count > team_count.")
    if league["veto_threshold"] >= team_count:
        raise err_invalid_state("veto_threshold must be < team_count.")

    # Side effects.
    league["status"] = "DRAFTING"
    teams.sort(key=lambda t: (t["created_at"], t.get("_seq", 0)))
    for idx, t in enumerate(teams):
        t["faab_balance_cents"] = league["faab_budget_cents"]
        t["waiver_priority"] = idx + 1
        bump(t)
    league["total_faab_pool_cents"] = league["faab_budget_cents"] * team_count
    bump(league)
    return success_object(serialize(league))


# ---------------- POST /leagues/{id}/finalize-draft ----------------

@bp.route("/leagues/<lid>/finalize-draft", methods=["POST"])
def finalize_draft(lid):
    require_role("Commissioner")
    league = get_league(lid)
    body = request.get_json(silent=True) or {}
    if league["status"] != "DRAFTING":
        raise err_invalid_state("League not in DRAFTING.")
    check_league_occ(league, body)

    teams = [t for t in store().teams.values() if t["league_id"] == lid]
    roster_size = int(league["roster_size"])
    for t in teams:
        team_picks = [
            dp for dp in store().draft_picks.values()
            if dp["league_id"] == lid and dp["team_id"] == t["id"]
        ]
        if len(team_picks) != roster_size:
            raise err_invalid_state(
                f"Team {t['id']} has {len(team_picks)} picks; expected {roster_size}."
            )
    # Side effects.
    league["status"] = "IN_SEASON"
    league["current_week"] = 1
    # Walk every draft pick in created_at order to create roster slots.
    all_picks = [dp for dp in store().draft_picks.values() if dp["league_id"] == lid]
    all_picks.sort(key=lambda dp: (dp["created_at"], dp.get("_seq", 0)))
    for dp in all_picks:
        player = store().players.get(dp["player_id"])
        if player is None:
            continue
        player["current_team_id"] = dp["team_id"]
        bump(player)
        create_roster_slot(
            team_id=dp["team_id"], player_id=dp["player_id"], slot_type="BENCH"
        )
    bump(league)
    return success_object(serialize(league))


# ---------------- POST /leagues/{id}/advance-week ----------------

@bp.route("/leagues/<lid>/advance-week", methods=["POST"])
def advance_week(lid):
    require_role("Commissioner")
    league = get_league(lid)
    body = request.get_json(silent=True) or {}
    if league["status"] != "IN_SEASON":
        raise err_invalid_state("League not in IN_SEASON.")
    check_league_occ(league, body)

    playoff_rounds = _round_count(league["playoff_team_count"])
    regular_weeks_cap = 17 - playoff_rounds
    if int(league["current_week"]) >= regular_weeks_cap:
        raise err_invalid_state("No regular-season weeks remaining.")
    # All regular matchups for current week must be COMPLETED.
    for m in store().matchups.values():
        if (
            m["league_id"] == lid
            and m["matchup_type"] == "REGULAR"
            and int(m["week"]) == int(league["current_week"])
            and m["state"] != "COMPLETED"
        ):
            raise err_invalid_state("Pending regular matchup for current week.")

    # Process waivers, then increment current_week.
    resolve_waiver_batch(league)
    league["current_week"] = int(league["current_week"]) + 1
    bump(league)
    return success_object(serialize(league))


# ---------------- POST /leagues/{id}/start-playoffs ----------------

@bp.route("/leagues/<lid>/start-playoffs", methods=["POST"])
def start_playoffs(lid):
    require_role("Commissioner")
    league = get_league(lid)
    body = request.get_json(silent=True) or {}
    if league["status"] != "IN_SEASON":
        raise err_invalid_state("League not in IN_SEASON.")
    check_league_occ(league, body)

    playoff_rounds = _round_count(league["playoff_team_count"])
    expected_cw = (17 - playoff_rounds) + 1
    if int(league["current_week"]) != expected_cw:
        raise err_invalid_state(
            f"current_week must equal {expected_cw} to start playoffs."
        )
    for m in store().matchups.values():
        if (
            m["league_id"] == lid
            and m["matchup_type"] == "REGULAR"
            and m["state"] != "COMPLETED"
        ):
            raise err_invalid_state("All regular matchups must be COMPLETED.")

    # Compute seeds.
    seeded = compute_playoff_seeds(league)
    for t in seeded:
        bump(t)
    # Auto-create round-1 PlayoffMatchup rows: seed 1 vs N, 2 vs N-1, etc.
    N = league["playoff_team_count"]
    top = [t for t in seeded if int(t.get("playoff_seed", 0)) > 0]
    top.sort(key=lambda t: int(t["playoff_seed"]))
    pairs = []
    for i in range(N // 2):
        high = top[i]
        low = top[N - 1 - i]
        pairs.append((high, low))
    week = int(league["current_week"])
    for high, low in pairs:
        common = new_common_fields(store().next_seq())
        m = {
            **common,
            "league_id": lid,
            "week": week,
            "matchup_type": "PLAYOFF",
            "round": 1,
            "home_team_id": high["id"],
            "away_team_id": low["id"],
            "home_score": 0,
            "away_score": 0,
            "state": "SCHEDULED",
            "winner_team_id": None,
        }
        store().matchups[m["id"]] = m

    league["status"] = "PLAYOFFS"
    bump(league)
    return success_object(serialize(league))


# ---------------- POST /leagues/{id}/finalize-season ----------------

@bp.route("/leagues/<lid>/finalize-season", methods=["POST"])
def finalize_season(lid):
    require_role("Commissioner")
    league = get_league(lid)
    body = request.get_json(silent=True) or {}
    if league["status"] != "PLAYOFFS":
        raise err_invalid_state("League not in PLAYOFFS.")
    check_league_occ(league, body)

    final_round = _round_count(league["playoff_team_count"])
    # Final-round matchup must exist and be COMPLETED.
    has_final = False
    for m in store().matchups.values():
        if (
            m["league_id"] == lid
            and m["matchup_type"] == "PLAYOFF"
            and int(m["round"]) == final_round
        ):
            if m["state"] == "COMPLETED":
                has_final = True
            else:
                raise err_invalid_state("Final-round matchup not yet COMPLETED.")
    if not has_final:
        raise err_invalid_state("No COMPLETED final-round matchup.")

    league["status"] = "COMPLETE"
    # Lock keepers: re-run dynasty_keeper_cost for each team that has keepers.
    teams = [t for t in store().teams.values() if t["league_id"] == lid]
    for t in teams:
        recompute_keeper_costs(t)
        bump(t)
    bump(league)
    return success_object(serialize(league))


# ---------------- GET /leagues/{id}/draft-board ----------------

@bp.route("/leagues/<lid>/draft-board", methods=["GET"])
def draft_board(lid):
    require_role("Commissioner", "TeamOwner")
    league = get_league(lid)
    position = request.args.get("position")
    limit, offset = parse_pagination()

    players = list(store().players.values())
    if position is not None:
        players = [p for p in players if p["position"] == position]
    entries = []
    for p in players:
        v = draft_pick_value(league, p)
        entries.append({
            "player_id": p["id"],
            "value": v["value"],
            "variant": v["variant"],
        })
    entries.sort(key=lambda e: (-float(e["value"]), e["player_id"]))
    total = len(entries)
    sliced = entries[offset:offset + limit]
    variant = "snake" if league["draft_type"] == "SNAKE" else "auction"
    payload = {"entries": sliced, "variant": variant}
    # Return as object with pagination fields in meta, like a list response.
    from response import success
    return success(
        payload,
        code=200,
        response_type="object",
        meta_extra={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(sliced)) < total,
        },
    )


# ---------------- GET /players/{id}/draft-value ----------------

@bp.route("/players/<pid>/draft-value", methods=["GET"])
def player_draft_value(pid):
    require_role("Commissioner", "TeamOwner")
    player = get_player(pid)
    league_id = request.args.get("league_id")
    if not league_id:
        raise err_invalid_request("league_id query param required.")
    league = get_league(league_id)
    v = draft_pick_value(league, player)
    payload = {"player_id": pid, "variant": v["variant"], "value": v["value"]}
    return success_object(payload)
