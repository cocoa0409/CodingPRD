"""Game endpoints: schedule, read, list, assign-referee, postpone, reschedule,
cancel, record-result, forfeit."""
from __future__ import annotations

from datetime import timedelta
from math import ceil, log2

from flask import Blueprint, g, request

from ..auth import require_roles
from ..calculations import (
    GAME_DURATION,
    field_overlap_check,
    referee_overlap_check,
    referee_weekly_count,
)
from ..errors import raise_error
from ..response import paginated_response, success_response
from ..services.aggregates import (
    recompute_guardian_volunteer,
    recompute_team_record,
)
from ..services.lookup import get_game, get_referee, get_season, get_team
from ..services.serializers import serialize_game
from ..store import get_store, new_id, stamp_create, stamp_update
from ..time_utils import format_iso, now_dt, parse_iso
from ..validation import (
    as_enum,
    as_int,
    as_iso_datetime,
    as_string,
    check_version_if_supplied,
    get_json_body,
    parse_pagination,
    require_fields,
)

game_bp = Blueprint("games", __name__)


GAME_TYPES = {"REGULAR", "PLAYOFF"}
POSTPONE_REASONS = {"RAIN", "FIELD_UNAVAILABLE", "SAFETY"}


# ---------------------------------------------------------------------------
# Create game
# ---------------------------------------------------------------------------
@game_bp.route("/league/games", methods=["POST"])
@require_roles(["LeagueAdmin"])
def create_game():
    body = get_json_body()
    require_fields(body, ["season_id", "home_team_id", "away_team_id", "field_id", "scheduled_start"])
    store = get_store()

    season = get_season(store, body["season_id"])
    home = get_team(store, body["home_team_id"]) if False else None
    # Use lookup for foreign key existence as ERR_REFERENCE_NOT_FOUND
    if body["home_team_id"] not in store.teams:
        raise_error("ERR_REFERENCE_NOT_FOUND", "home_team_id not found.")
    if body["away_team_id"] not in store.teams:
        raise_error("ERR_REFERENCE_NOT_FOUND", "away_team_id not found.")
    home = store.teams[body["home_team_id"]]
    away = store.teams[body["away_team_id"]]

    game_type = "REGULAR"
    if "game_type" in body and body["game_type"] is not None:
        game_type = as_enum(body["game_type"], "game_type", GAME_TYPES)

    field_id = as_string(body["field_id"], "field_id", min_len=1, max_len=40)
    scheduled_start_dt = as_iso_datetime(body["scheduled_start"], "scheduled_start")

    if home["id"] == away["id"]:
        raise_error("ERR_INVALID_GAME_OPPONENTS")

    # Regular game window check.
    if game_type == "REGULAR":
        rs_start = parse_iso(season["regular_season_start"])
        rs_end = parse_iso(season["regular_season_end"])
        if scheduled_start_dt < rs_start or scheduled_start_dt > rs_end:
            raise_error("ERR_GAME_OUT_OF_SEASON_WINDOW")

    scheduled_end_dt = scheduled_start_dt + GAME_DURATION

    # Field overlap check.
    if field_overlap_check(scheduled_start_dt, scheduled_end_dt, field_id, store.games.values()):
        raise_error("ERR_FIELD_OVERLAP")

    game = {
        "id": new_id(),
        "season_id": season["id"],
        "home_team_id": home["id"],
        "away_team_id": away["id"],
        "game_type": game_type,
        "field_id": field_id,
        "scheduled_start": format_iso(scheduled_start_dt),
        "scheduled_end": format_iso(scheduled_end_dt),
        "original_scheduled_start": format_iso(scheduled_start_dt),
        "referee_id": None,
        "status": "SCHEDULED",
        "home_score": None,
        "away_score": None,
        "bracket_round": None,
        "forfeiting_team_id": None,
    }
    stamp_create(game)
    store.games[game["id"]] = game
    store.record_audit("Game", game["id"], g.role, g.user_id, "GAME_SCHEDULED", {})
    return success_response(serialize_game(game), status_code=201)


# ---------------------------------------------------------------------------
# Read game
# ---------------------------------------------------------------------------
@game_bp.route("/league/games/<game_id>", methods=["GET"])
@require_roles(["LeagueAdmin", "Coach", "Referee", "Guardian"])
def read_game(game_id: str):
    store = get_store()
    game = get_game(store, game_id)
    return success_response(serialize_game(game), status_code=200)


# ---------------------------------------------------------------------------
# List games
# ---------------------------------------------------------------------------
@game_bp.route("/league/games", methods=["GET"])
@require_roles(["LeagueAdmin", "Coach", "Referee", "Guardian"])
def list_games():
    store = get_store()
    limit, offset = parse_pagination()
    season_id = request.args.get("season_id")
    team_id = request.args.get("team_id")
    referee_id = request.args.get("referee_id")
    status = request.args.get("status")
    field_id = request.args.get("field_id")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")
    from_dt = parse_iso(from_date) if from_date else None
    to_dt = parse_iso(to_date) if to_date else None

    results = []
    for gm in store.games.values():
        if season_id and gm["season_id"] != season_id:
            continue
        if team_id and team_id not in (gm["home_team_id"], gm["away_team_id"]):
            continue
        if referee_id and gm.get("referee_id") != referee_id:
            continue
        if status and gm["status"] != status:
            continue
        if field_id and gm["field_id"] != field_id:
            continue
        if from_dt or to_dt:
            gs = parse_iso(gm["scheduled_start"])
            if from_dt and gs < from_dt:
                continue
            if to_dt and gs > to_dt:
                continue
        results.append(gm)
    results.sort(key=lambda x: x["created_at"])
    total = len(results)
    page = results[offset : offset + limit]
    return paginated_response([serialize_game(x) for x in page], total, limit, offset)


# ---------------------------------------------------------------------------
# assign-referee
# ---------------------------------------------------------------------------
@game_bp.route("/league/games/<game_id>/assign-referee", methods=["POST"])
@require_roles(["LeagueAdmin"])
def assign_referee(game_id: str):
    store = get_store()
    game = get_game(store, game_id)
    body = get_json_body()
    require_fields(body, ["referee_id"])
    ref = get_referee(store, body["referee_id"])

    if game["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "Game must be SCHEDULED.")

    check_version_if_supplied(game, body)

    if game.get("referee_id") is not None:
        raise_error("ERR_GAME_REFEREE_ALREADY_ASSIGNED")

    target_start = parse_iso(game["scheduled_start"])
    target_end = parse_iso(game["scheduled_end"])

    if referee_overlap_check(target_start, target_end, ref["id"], store.games.values(), exclude_game_id=game["id"]):
        raise_error("ERR_REFEREE_OVERLAP")

    week_count = referee_weekly_count(ref["id"], target_start, store.games.values(), exclude_game_id=game["id"])
    if week_count + 1 > ref["weekly_assignment_cap"]:
        raise_error("ERR_REFEREE_WEEKLY_CAP_EXCEEDED")

    game["referee_id"] = ref["id"]
    stamp_update(game)
    store.record_audit("Game", game["id"], g.role, g.user_id, "REFEREE_ASSIGNED", {"referee_id": ref["id"]})
    return success_response(serialize_game(game), status_code=200)


# ---------------------------------------------------------------------------
# postpone
# ---------------------------------------------------------------------------
@game_bp.route("/league/games/<game_id>/postpone", methods=["POST"])
@require_roles(["LeagueAdmin"])
def postpone_game(game_id: str):
    store = get_store()
    game = get_game(store, game_id)
    body = get_json_body()
    require_fields(body, ["reason"])
    as_enum(body["reason"], "reason", POSTPONE_REASONS)

    if game["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "Only SCHEDULED games can be postponed.")
    season = get_season(store, game["season_id"])
    if season["status"] not in ("REGULAR_SEASON", "PLAYOFFS"):
        raise_error("ERR_INVALID_STATE", "Season must be REGULAR_SEASON or PLAYOFFS to postpone.")

    check_version_if_supplied(game, body)

    game["status"] = "POSTPONED"
    game["referee_id"] = None
    stamp_update(game)

    # Cascade: cancel linked SCHEDULED VolunteerShifts and recompute guardians.
    touched_guardian_ids: set[str] = set()
    for shift in store.shifts.values():
        if shift.get("game_id") == game["id"] and shift["status"] == "SCHEDULED":
            shift["status"] = "CANCELLED"
            stamp_update(shift)
            touched_guardian_ids.add(shift["guardian_id"])
    for gid in touched_guardian_ids:
        gn = store.guardians.get(gid)
        if gn:
            recompute_guardian_volunteer(store, gn, season["id"])

    store.record_audit(
        "Game", game["id"], g.role, g.user_id, "GAME_POSTPONED", {"reason": body["reason"]}
    )
    return success_response(serialize_game(game), status_code=200)


# ---------------------------------------------------------------------------
# reschedule
# ---------------------------------------------------------------------------
@game_bp.route("/league/games/<game_id>/reschedule", methods=["POST"])
@require_roles(["LeagueAdmin"])
def reschedule_game(game_id: str):
    store = get_store()
    game = get_game(store, game_id)
    body = get_json_body()
    require_fields(body, ["scheduled_start"])
    new_start = as_iso_datetime(body["scheduled_start"], "scheduled_start")
    new_referee_id = body.get("referee_id")
    new_field_id = body.get("field_id")

    if game["status"] != "POSTPONED":
        raise_error("ERR_INVALID_STATE", "Only POSTPONED games can be rescheduled.")

    check_version_if_supplied(game, body)

    season = get_season(store, game["season_id"])
    orig = parse_iso(game["original_scheduled_start"])
    window_end = orig + timedelta(days=int(season["rainout_window_days"]))
    if not (new_start > orig and new_start <= window_end):
        raise_error("ERR_RAINOUT_WINDOW_EXCEEDED")

    new_end = new_start + GAME_DURATION
    field_id = new_field_id if new_field_id else game["field_id"]
    if new_field_id is not None:
        field_id = as_string(new_field_id, "field_id", min_len=1, max_len=40)

    # Need to temporarily ignore current game's slot since it is POSTPONED — but our
    # field_overlap_check already excludes POSTPONED games. We exclude this game
    # explicitly anyway.
    if field_overlap_check(new_start, new_end, field_id, store.games.values(), exclude_game_id=game["id"]):
        raise_error("ERR_FIELD_OVERLAP")

    referee_id_final = None
    if new_referee_id is not None:
        ref = get_referee(store, new_referee_id)
        if referee_overlap_check(new_start, new_end, ref["id"], store.games.values(), exclude_game_id=game["id"]):
            raise_error("ERR_REFEREE_OVERLAP")
        week_count = referee_weekly_count(ref["id"], new_start, store.games.values(), exclude_game_id=game["id"])
        if week_count + 1 > ref["weekly_assignment_cap"]:
            raise_error("ERR_REFEREE_WEEKLY_CAP_EXCEEDED")
        referee_id_final = ref["id"]

    game["scheduled_start"] = format_iso(new_start)
    game["scheduled_end"] = format_iso(new_end)
    game["field_id"] = field_id
    game["status"] = "SCHEDULED"
    game["referee_id"] = referee_id_final
    stamp_update(game)
    store.record_audit("Game", game["id"], g.role, g.user_id, "GAME_RESCHEDULED", {})
    return success_response(serialize_game(game), status_code=200)


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------
@game_bp.route("/league/games/<game_id>/cancel", methods=["POST"])
@require_roles(["LeagueAdmin"])
def cancel_game(game_id: str):
    store = get_store()
    game = get_game(store, game_id)
    body = get_json_body()
    if game["status"] != "POSTPONED":
        raise_error("ERR_INVALID_STATE", "Only POSTPONED games can be cancelled.")

    check_version_if_supplied(game, body)

    season = get_season(store, game["season_id"])
    orig = parse_iso(game["original_scheduled_start"])
    window_end = orig + timedelta(days=int(season["rainout_window_days"]))
    if now_dt() <= window_end:
        raise_error("ERR_INVALID_STATE", "Rainout window has not yet elapsed.")

    game["status"] = "CANCELLED"
    stamp_update(game)
    store.record_audit("Game", game["id"], g.role, g.user_id, "GAME_CANCELLED", {})
    return success_response(serialize_game(game), status_code=200)


# ---------------------------------------------------------------------------
# record-result
# ---------------------------------------------------------------------------
def _handle_playoff_advancement(store, game, season):
    """After a PLAYOFF game terminates, update playoff_status and possibly create next round."""
    home = store.teams.get(game["home_team_id"])
    away = store.teams.get(game["away_team_id"])
    if home is None or away is None:
        return
    # Determine winner / loser.
    if game["status"] == "COMPLETED":
        hs = game.get("home_score") or 0
        as_ = game.get("away_score") or 0
        winner, loser = (home, away) if hs > as_ else (away, home)
    elif game["status"] == "FORFEITED":
        forfeit = game.get("forfeiting_team_id")
        if forfeit == home["id"]:
            winner, loser = away, home
        else:
            winner, loser = home, away
    else:
        return

    qualified_count = sum(
        1
        for t in store.teams.values()
        if t["season_id"] == season["id"] and t.get("playoff_seed") is not None
    )
    final_round = int(ceil(log2(qualified_count))) if qualified_count > 1 else 1
    current_round = game.get("bracket_round") or 1

    # Loser eliminated.
    loser["playoff_status"] = "ELIMINATED"
    stamp_update(loser)

    if current_round >= final_round:
        winner["playoff_status"] = "CHAMPION"
        stamp_update(winner)
        return

    # Otherwise, find the sibling game in this round whose winner feeds the same next-round slot.
    sibling = None
    for gm in store.games.values():
        if gm["id"] == game["id"]:
            continue
        if gm.get("game_type") != "PLAYOFF":
            continue
        if gm["season_id"] != season["id"]:
            continue
        if gm.get("bracket_round") != current_round:
            continue
        sibling = gm
        break
    if sibling is None or sibling.get("status") not in ("COMPLETED", "FORFEITED"):
        # Defer next-round creation.
        return

    # Sibling completed; determine sibling winner.
    sh = store.teams.get(sibling["home_team_id"])
    sa = store.teams.get(sibling["away_team_id"])
    if sibling["status"] == "COMPLETED":
        shs = sibling.get("home_score") or 0
        sas = sibling.get("away_score") or 0
        sibling_winner = sh if shs > sas else sa
    else:  # FORFEITED
        forfeit = sibling.get("forfeiting_team_id")
        sibling_winner = sa if forfeit == sh["id"] else sh

    base_dt = max(parse_iso(game["scheduled_end"]), parse_iso(sibling["scheduled_end"]))
    new_start = base_dt + timedelta(days=7)
    new_end = new_start + GAME_DURATION

    next_game_id = new_id()
    next_game = {
        "id": next_game_id,
        "season_id": season["id"],
        "home_team_id": winner["id"],
        "away_team_id": sibling_winner["id"],
        "game_type": "PLAYOFF",
        "field_id": "TBD",
        "scheduled_start": format_iso(new_start),
        "scheduled_end": format_iso(new_end),
        "original_scheduled_start": format_iso(new_start),
        "referee_id": None,
        "status": "SCHEDULED",
        "home_score": None,
        "away_score": None,
        "bracket_round": current_round + 1,
        "forfeiting_team_id": None,
    }
    stamp_create(next_game)
    store.games[next_game_id] = next_game
    store.record_audit(
        "Game",
        next_game_id,
        None,
        None,
        "PLAYOFF_BRACKET_GAME_CREATED",
        {"bracket_round": current_round + 1},
    )


@game_bp.route("/league/games/<game_id>/record-result", methods=["POST"])
@require_roles(["LeagueAdmin"])
def record_result(game_id: str):
    store = get_store()
    game = get_game(store, game_id)
    body = get_json_body()
    require_fields(body, ["home_score", "away_score"])

    if game["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "Only SCHEDULED games can be recorded.")

    check_version_if_supplied(game, body)

    hs = body["home_score"]
    as_ = body["away_score"]
    if isinstance(hs, bool) or isinstance(as_, bool) or not isinstance(hs, int) or not isinstance(as_, int):
        raise_error("ERR_INVALID_SCORE")
    if hs < 0 or as_ < 0 or hs == as_:
        raise_error("ERR_INVALID_SCORE")
    if game.get("referee_id") is None:
        raise_error("ERR_GAME_REFEREE_REQUIRED")

    scheduled_end = parse_iso(game["scheduled_end"])
    if now_dt() < scheduled_end:
        raise_error("ERR_INVALID_STATE", "Cannot record result before scheduled_end.")

    game["home_score"] = hs
    game["away_score"] = as_
    game["status"] = "COMPLETED"
    stamp_update(game)

    # Team records.
    home = store.teams.get(game["home_team_id"])
    away = store.teams.get(game["away_team_id"])
    if home:
        recompute_team_record(store, home)
    if away:
        recompute_team_record(store, away)

    # Playoff bracket advancement.
    if game["game_type"] == "PLAYOFF":
        season = store.seasons.get(game["season_id"])
        _handle_playoff_advancement(store, game, season)

    store.record_audit(
        "Game", game["id"], g.role, g.user_id, "GAME_RESULT_RECORDED",
        {"home_score": hs, "away_score": as_},
    )
    return success_response(serialize_game(game), status_code=200)


# ---------------------------------------------------------------------------
# forfeit
# ---------------------------------------------------------------------------
@game_bp.route("/league/games/<game_id>/forfeit", methods=["POST"])
@require_roles(["LeagueAdmin"])
def forfeit_game(game_id: str):
    store = get_store()
    game = get_game(store, game_id)
    body = get_json_body()
    require_fields(body, ["forfeiting_team_id"])
    forfeit_team_id = body["forfeiting_team_id"]

    if forfeit_team_id not in (game["home_team_id"], game["away_team_id"]):
        raise_error("ERR_VALIDATION", "forfeiting_team_id must be one of the game's teams.")

    if game["status"] != "SCHEDULED":
        raise_error("ERR_INVALID_STATE", "Only SCHEDULED games can be forfeited.")

    check_version_if_supplied(game, body)

    game["status"] = "FORFEITED"
    game["forfeiting_team_id"] = forfeit_team_id
    stamp_update(game)

    home = store.teams.get(game["home_team_id"])
    away = store.teams.get(game["away_team_id"])
    if home:
        recompute_team_record(store, home)
    if away:
        recompute_team_record(store, away)

    if game["game_type"] == "PLAYOFF":
        season = store.seasons.get(game["season_id"])
        _handle_playoff_advancement(store, game, season)

    store.record_audit(
        "Game", game["id"], g.role, g.user_id, "GAME_FORFEITED", {"forfeiting_team_id": forfeit_team_id}
    )
    return success_response(serialize_game(game), status_code=200)
