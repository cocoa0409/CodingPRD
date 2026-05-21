"""Season endpoints + lifecycle transitions."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

from ..auth import require_roles
from ..calculations import (
    PLAYOFF_BRACKET_SIZE,
    GAME_DURATION,
    playoff_seeding,
)
from ..errors import raise_error
from ..response import success_response
from ..services.aggregates import recompute_team_record
from ..services.lookup import get_season
from ..services.serializers import serialize_season
from ..store import get_store, new_id, stamp_create, stamp_update
from ..time_utils import format_iso, now_dt, parse_iso
from ..validation import (
    as_enum,
    as_int,
    as_iso_datetime,
    as_number,
    as_string,
    get_json_body,
    require_fields,
)

season_bp = Blueprint("seasons", __name__)


AGE_DIVISIONS = {"TBALL", "MINORS", "MAJORS", "INTERMEDIATE", "JUNIORS"}


def _season_create_inputs(body: dict) -> dict:
    require_fields(
        body,
        [
            "name",
            "age_division",
            "min_birth_date",
            "max_birth_date",
            "regular_season_start",
            "regular_season_end",
            "playoff_cutoff_date",
        ],
    )
    name = as_string(body["name"], "name", min_len=1, max_len=120)
    age_division = as_enum(body["age_division"], "age_division", AGE_DIVISIONS)
    min_birth = as_iso_datetime(body["min_birth_date"], "min_birth_date")
    max_birth = as_iso_datetime(body["max_birth_date"], "max_birth_date")
    rs_start = as_iso_datetime(body["regular_season_start"], "regular_season_start")
    rs_end = as_iso_datetime(body["regular_season_end"], "regular_season_end")
    playoff_cutoff = as_iso_datetime(body["playoff_cutoff_date"], "playoff_cutoff_date")

    rainout = 14
    if "rainout_window_days" in body and body["rainout_window_days"] is not None:
        rainout = as_int(body["rainout_window_days"], "rainout_window_days", minimum=1, maximum=60)
    vol_required = Decimal("6.0")
    if "volunteer_hours_required_per_family" in body and body["volunteer_hours_required_per_family"] is not None:
        n = as_number(body["volunteer_hours_required_per_family"], "volunteer_hours_required_per_family", minimum=0, maximum=100)
        vol_required = Decimal(str(n)).quantize(Decimal("0.01"))

    store = get_store()
    for s in store.seasons.values():
        if s["name"] == name:
            raise_error("ERR_VALIDATION", "Season name already exists.")

    return {
        "name": name,
        "age_division": age_division,
        "min_birth_date": format_iso(min_birth),
        "max_birth_date": format_iso(max_birth),
        "regular_season_start": format_iso(rs_start),
        "regular_season_end": format_iso(rs_end),
        "playoff_cutoff_date": format_iso(playoff_cutoff),
        "rainout_window_days": rainout,
        "volunteer_hours_required_per_family": vol_required,
    }


@season_bp.route("/league/seasons", methods=["POST"])
@require_roles(["LeagueAdmin"])
def create_season():
    body = get_json_body()
    fields = _season_create_inputs(body)
    season = {
        **fields,
        "id": new_id(),
        "status": "DRAFT_OPEN",
    }
    stamp_create(season)
    get_store().seasons[season["id"]] = season
    get_store().record_audit(
        "Season", season["id"], g.role, g.user_id, "SEASON_CREATED", {}
    )
    return success_response(serialize_season(season), status_code=201)


@season_bp.route("/league/seasons/<season_id>", methods=["GET"])
@require_roles(["LeagueAdmin", "Coach", "Referee", "Guardian"])
def read_season(season_id: str):
    s = get_season(get_store(), season_id)
    return success_response(serialize_season(s), status_code=200)


# ---------------------------------------------------------------------------
# start-regular-season
# ---------------------------------------------------------------------------
@season_bp.route("/league/seasons/<season_id>/start-regular-season", methods=["POST"])
@require_roles(["LeagueAdmin"])
def start_regular_season(season_id: str):
    store = get_store()
    season = get_season(store, season_id)
    if season["status"] != "DRAFT_OPEN":
        raise_error("ERR_INVALID_STATE", "Season is not in DRAFT_OPEN.")

    teams_in_season = [t for t in store.teams.values() if t["season_id"] == season_id]
    if len(teams_in_season) < 4:
        raise_error("ERR_SEASON_NOT_READY", "Less than 4 teams in season.")
    for t in teams_in_season:
        if t.get("roster_count", 0) < 8:
            raise_error("ERR_SEASON_NOT_READY", "A team has roster_count < 8.")

    # Auto-withdraw any non-WITHDRAWN, non-DRAFTED players in this season.
    for p in list(store.players.values()):
        if p["season_id"] != season_id:
            continue
        if p["status"] in ("DRAFTED", "WITHDRAWN"):
            continue
        # In particular EVALUATED but not DRAFTED → WITHDRAWN.
        if p["status"] == "EVALUATED":
            p["status"] = "WITHDRAWN"
            stamp_update(p)
            store.record_audit(
                "Player", p["id"], g.role, g.user_id, "PLAYER_AUTO_WITHDRAWN", {}
            )
        else:
            # Players still in PENDING_VERIFICATION/AGE_VERIFIED also block; treat as not-ready.
            raise_error(
                "ERR_INVALID_STATE",
                "Players exist that are neither WITHDRAWN nor DRAFTED.",
            )

    season["status"] = "REGULAR_SEASON"
    stamp_update(season)
    store.record_audit("Season", season["id"], g.role, g.user_id, "SEASON_REGULAR_OPENED", {})
    return success_response(serialize_season(season), status_code=200)


# ---------------------------------------------------------------------------
# start-playoffs
# ---------------------------------------------------------------------------
@season_bp.route("/league/seasons/<season_id>/start-playoffs", methods=["POST"])
@require_roles(["LeagueAdmin"])
def start_playoffs(season_id: str):
    store = get_store()
    season = get_season(store, season_id)
    if season["status"] != "REGULAR_SEASON":
        raise_error("ERR_INVALID_STATE", "Season must be in REGULAR_SEASON to open playoffs.")

    # Clock guard: now() >= playoff_cutoff_date
    cutoff = parse_iso(season["playoff_cutoff_date"])
    if now_dt() < cutoff:
        raise_error("ERR_INVALID_STATE", "Playoff cutoff date has not been reached.")

    # All regular games must be terminal.
    for gm in store.games.values():
        if gm["season_id"] != season_id:
            continue
        if gm.get("game_type") != "REGULAR":
            continue
        if gm["status"] not in ("COMPLETED", "FORFEITED", "CANCELLED"):
            raise_error("ERR_REGULAR_SEASON_INCOMPLETE")

    # Recompute team records.
    teams_in_season = [t for t in store.teams.values() if t["season_id"] == season_id]
    for t in teams_in_season:
        recompute_team_record(store, t)

    # Seed top 4.
    games_in_season = [gm for gm in store.games.values() if gm["season_id"] == season_id]
    sorted_teams = playoff_seeding(teams_in_season, games_in_season)
    top4 = sorted_teams[:PLAYOFF_BRACKET_SIZE]
    rest = sorted_teams[PLAYOFF_BRACKET_SIZE:]
    for i, t in enumerate(top4, start=1):
        t["playoff_seed"] = i
        t["playoff_status"] = "QUALIFIED"
        stamp_update(t)
    for t in rest:
        t["playoff_status"] = "ELIMINATED"
        stamp_update(t)

    season["status"] = "PLAYOFFS"
    stamp_update(season)

    # Generate round-1 bracket: 1v4 and 2v3.
    if len(top4) >= 4:
        bracket_start = parse_iso(season["playoff_cutoff_date"]) + timedelta(days=7)
        bracket_iso = format_iso(bracket_start)
        end_iso = format_iso(bracket_start + GAME_DURATION)
        for home, away in ((top4[0], top4[3]), (top4[1], top4[2])):
            gid = new_id()
            game = {
                "id": gid,
                "season_id": season_id,
                "home_team_id": home["id"],
                "away_team_id": away["id"],
                "game_type": "PLAYOFF",
                "field_id": "TBD",
                "scheduled_start": bracket_iso,
                "scheduled_end": end_iso,
                "original_scheduled_start": bracket_iso,
                "referee_id": None,
                "status": "SCHEDULED",
                "home_score": None,
                "away_score": None,
                "bracket_round": 1,
                "forfeiting_team_id": None,
            }
            stamp_create(game)
            store.games[gid] = game
            store.record_audit(
                "Game", gid, g.role, g.user_id, "PLAYOFF_BRACKET_GAME_CREATED",
                {"bracket_round": 1, "home": home["id"], "away": away["id"]},
            )

    store.record_audit("Season", season["id"], g.role, g.user_id, "PLAYOFFS_OPENED", {})
    return success_response(serialize_season(season), status_code=200)


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------
@season_bp.route("/league/seasons/<season_id>/close", methods=["POST"])
@require_roles(["LeagueAdmin"])
def close_season(season_id: str):
    store = get_store()
    season = get_season(store, season_id)
    if season["status"] != "PLAYOFFS":
        raise_error("ERR_INVALID_STATE", "Season must be in PLAYOFFS to close.")

    teams_in_season = [t for t in store.teams.values() if t["season_id"] == season_id]
    champions = [t for t in teams_in_season if t.get("playoff_status") == "CHAMPION"]
    if len(champions) != 1:
        raise_error("ERR_INVALID_STATE", "Exactly one team must be CHAMPION to close.")
    for t in teams_in_season:
        if t.get("playoff_status") not in ("CHAMPION", "ELIMINATED"):
            raise_error("ERR_INVALID_STATE", "All non-CHAMPION teams must be ELIMINATED.")

    season["status"] = "CLOSED"
    stamp_update(season)
    store.record_audit("Season", season["id"], g.role, g.user_id, "SEASON_CLOSED", {})
    return success_response(serialize_season(season), status_code=200)
