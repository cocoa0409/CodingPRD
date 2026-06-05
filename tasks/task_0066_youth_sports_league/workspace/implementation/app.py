"""Youth Sports League API — Flask entry point, routes, and business logic."""
import os

from flask import Flask, request

from errors import ApiError, err
from response import object_response, array_response, error_response
from store import store, new_id, now_iso
from auth import get_identity, require_roles
from helpers import (
    get_json_body,
    require_fields,
    require_string,
    require_int,
    optional_int,
    paginate,
    apply_pagination,
    base_record,
    touch,
)
import calculations as calc
import serializers as ser

app = Flask(__name__)


# =============================================================================
# Error handling
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", 400, str(e))


# =============================================================================
# Auth + RBAC helpers
# =============================================================================
def auth(allowed_roles):
    """Authenticate and authorize the role. Returns (user_id, role)."""
    user_id, role = get_identity()
    require_roles(role, allowed_roles)
    return user_id, role


# =============================================================================
# Lookup helpers (existence -> ERR_NOT_FOUND)
# =============================================================================
def get_or_404(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def find_league(league_id):
    return get_or_404(store.leagues, league_id)


# =============================================================================
# Computed counters
# =============================================================================
def recompute_total_registered(league):
    count = sum(
        1 for p in store.players.values()
        if p["league_id"] == league["id"] and p["status"] != "WITHDRAWN"
    )
    league["total_registered_players"] = count


# =============================================================================
# Validation helpers
# =============================================================================
VALID_ROLES = {"LeagueAdmin", "Coach", "Referee", "ParentGuardian"}


def validate_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} has invalid value")
    return value


# =============================================================================
# League endpoints
# =============================================================================
@app.route("/leagues", methods=["POST"])
def create_league():
    auth(["LeagueAdmin"])
    body = get_json_body()
    require_fields(body, [
        "name", "season_year", "age_cutoff_date",
        "registration_open_iso", "registration_close_iso",
    ])
    name = require_string(body, "name")
    season_year = require_int(body, "season_year")
    age_cutoff_date = require_string(body, "age_cutoff_date")
    reg_open = require_string(body, "registration_open_iso")
    reg_close = require_string(body, "registration_close_iso")
    draft_snake = body.get("draft_snake", True)
    if not isinstance(draft_snake, bool):
        raise err("ERR_INVALID_REQUEST", "draft_snake must be a boolean")
    # validate date / datetime parseability
    try:
        calc.parse_date(age_cutoff_date)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "age_cutoff_date must be YYYY-MM-DD")
    try:
        calc.parse_iso(reg_open)
        calc.parse_iso(reg_close)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "registration window must be ISO 8601")

    rec = base_record()
    rec.update({
        "name": name,
        "season_year": season_year,
        "age_cutoff_date": age_cutoff_date,
        "registration_open_iso": reg_open,
        "registration_close_iso": reg_close,
        "draft_snake": draft_snake,
        "status": "SETUP",
        "total_registered_players": 0,
        "draft_round_index": 0,
    })
    store.leagues[rec["id"]] = rec
    return object_response(ser.league_out(rec), 201)


@app.route("/leagues/<league_id>", methods=["GET"])
def get_league(league_id):
    auth(["LeagueAdmin", "Coach", "Referee", "ParentGuardian"])
    rec = find_league(league_id)
    return object_response(ser.league_out(rec), 200)


LEAGUE_ORDER = ["SETUP", "REGISTRATION", "EVALUATION", "DRAFT",
                "SEASON", "PLAYOFFS", "CLOSED"]


@app.route("/leagues/<league_id>/advance", methods=["POST"])
def advance_league(league_id):
    auth(["LeagueAdmin"])
    league = find_league(league_id)
    body = get_json_body()
    require_fields(body, ["target"])
    target = require_string(body, "target")
    if target not in LEAGUE_ORDER:
        raise err("ERR_INVALID_REQUEST", "Invalid target status")

    cur = league["status"]
    cur_idx = LEAGUE_ORDER.index(cur)
    # must be the immediate next phase
    if cur_idx + 1 >= len(LEAGUE_ORDER) or LEAGUE_ORDER[cur_idx + 1] != target:
        raise err("ERR_INVALID_STATE", "Illegal league advance")

    # preconditions per transition
    if target == "REGISTRATION":
        has_div = any(d["league_id"] == league_id for d in store.divisions.values())
        if not has_div:
            raise err("ERR_INVALID_STATE", "At least one division required")
    elif target == "DRAFT":
        for p in store.players.values():
            if p["league_id"] != league_id or p["status"] == "WITHDRAWN":
                continue
            if p["status"] != "EVALUATED":
                raise err("ERR_INVALID_STATE", "All players must be EVALUATED")
    elif target == "SEASON":
        for p in store.players.values():
            if p["league_id"] != league_id or p["status"] == "WITHDRAWN":
                continue
            if p["status"] not in ("DRAFTED", "ROSTERED"):
                raise err("ERR_INVALID_STATE", "All players must be DRAFTED/ROSTERED")
    elif target == "PLAYOFFS":
        for g in store.games.values():
            if g["league_id"] != league_id:
                continue
            if g["game_type"] == "REGULAR" and g["status"] in ("SCHEDULED", "IN_PROGRESS"):
                raise err("ERR_INVALID_STATE", "All regular games must be complete")
    elif target == "CLOSED":
        for g in store.games.values():
            if g["league_id"] != league_id:
                continue
            if g["game_type"] == "PLAYOFF" and g["status"] in ("SCHEDULED", "IN_PROGRESS"):
                raise err("ERR_INVALID_STATE", "All playoff games must be complete")

    # apply transition + side effects
    league["status"] = target
    if target == "DRAFT":
        league["draft_round_index"] = 0
    elif target == "SEASON":
        # cascade DRAFTED -> ROSTERED
        for p in store.players.values():
            if p["league_id"] == league_id and p["status"] == "DRAFTED":
                p["status"] = "ROSTERED"
                touch(p)
    elif target == "PLAYOFFS":
        compute_playoff_seeding(league)
    elif target == "CLOSED":
        settle_family_refunds(league)

    touch(league)
    return object_response(ser.league_out(league), 200)


def compute_playoff_seeding(league):
    use_win_pct = league["draft_snake"]
    # group teams by division
    by_div = {}
    for t in store.teams.values():
        if t["league_id"] != league["id"]:
            continue
        by_div.setdefault(t["division_id"], []).append(t)
    for div_id, teams in by_div.items():
        # recompute records from FINAL REGULAR games only
        def sort_key(t):
            wins = t["wins"]
            losses = t["losses"]
            if use_win_pct:
                decided = wins + losses
                primary = (wins / decided) if decided > 0 else 0.0
            else:
                primary = wins
            return (-primary, -t["run_differential"], t["created_at"])
        teams_sorted = sorted(teams, key=sort_key)
        for i, t in enumerate(teams_sorted):
            t["seed"] = i + 1
            touch(t)


def settle_family_refunds(league):
    for fam in store.families.values():
        if fam["league_id"] != league["id"]:
            continue
        fulfilled = [
            c for c in store.volunteer_commitments.values()
            if c["family_id"] == fam["id"] and c["status"] == "FULFILLED"
        ]
        fulfilled.sort(key=lambda c: c["created_at"])
        net = 0
        for c in fulfilled:
            fee = calc.volunteer_fee(c["credit_cents"])
            net += c["credit_cents"] - fee
        refund = min(net, fam["volunteer_deposit_cents"])
        # store refund as credit settlement (running credit reflects settlement)
        fam["volunteer_credit_cents"] = refund
        touch(fam)


@app.route("/_clock/set", methods=["POST"])
def set_clock():
    auth(["LeagueAdmin"])
    body = get_json_body()
    require_fields(body, ["now_iso"])
    now_iso_val = require_string(body, "now_iso")
    try:
        dt = calc.parse_iso(now_iso_val)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "now_iso must be ISO 8601")
    store.clock = dt
    return object_response({}, 200)


# =============================================================================
# Division endpoints
# =============================================================================
@app.route("/divisions", methods=["POST"])
def create_division():
    auth(["LeagueAdmin"])
    body = get_json_body()
    require_fields(body, [
        "league_id", "name", "min_league_age", "max_league_age", "roster_cap",
    ])
    league_id = require_string(body, "league_id")
    name = require_string(body, "name")
    min_age = require_int(body, "min_league_age")
    max_age = require_int(body, "max_league_age")
    roster_cap = require_int(body, "roster_cap")
    find_league(league_id)

    rec = base_record()
    rec.update({
        "league_id": league_id,
        "name": name,
        "min_league_age": min_age,
        "max_league_age": max_age,
        "roster_cap": roster_cap,
    })
    store.divisions[rec["id"]] = rec
    return object_response(ser.division_out(rec), 201)


@app.route("/divisions", methods=["GET"])
def list_divisions():
    auth(["LeagueAdmin", "Coach", "Referee", "ParentGuardian"])
    items = list(store.divisions.values())
    league_id = request.args.get("league_id")
    if league_id is not None:
        items = [d for d in items if d["league_id"] == league_id]
    return list_response(items, ser.division_out)


@app.route("/divisions/<division_id>", methods=["GET"])
def get_division(division_id):
    auth(["LeagueAdmin", "Coach", "Referee", "ParentGuardian"])
    rec = get_or_404(store.divisions, division_id)
    return object_response(ser.division_out(rec), 200)


# =============================================================================
# Family endpoints
# =============================================================================
@app.route("/families", methods=["POST"])
def create_family():
    user_id, role = auth(["LeagueAdmin", "ParentGuardian"])
    body = get_json_body()
    require_fields(body, [
        "league_id", "guardian_email", "guardian_name", "volunteer_deposit_cents",
    ])
    league_id = require_string(body, "league_id")
    guardian_email = require_string(body, "guardian_email")
    guardian_name = require_string(body, "guardian_name")
    deposit = require_int(body, "volunteer_deposit_cents")
    find_league(league_id)

    # duplicate email within league
    for f in store.families.values():
        if f["league_id"] == league_id and f["guardian_email"] == guardian_email:
            raise err("ERR_DUPLICATE_FAMILY_EMAIL", "guardian_email already used")

    rec = base_record()
    rec.update({
        "league_id": league_id,
        "guardian_email": guardian_email,
        "guardian_name": guardian_name,
        "volunteer_deposit_cents": deposit,
        "volunteer_credit_cents": 0,
    })
    store.families[rec["id"]] = rec
    return object_response(ser.family_out(rec), 201)


@app.route("/families", methods=["GET"])
def list_families():
    user_id, role = auth(["LeagueAdmin", "ParentGuardian"])
    items = list(store.families.values())
    league_id = request.args.get("league_id")
    if league_id is not None:
        items = [f for f in items if f["league_id"] == league_id]
    if role == "ParentGuardian":
        items = [f for f in items if f["id"] == user_id]
    return list_response(items, ser.family_out)


@app.route("/families/<family_id>", methods=["GET"])
def get_family(family_id):
    user_id, role = auth(["LeagueAdmin", "ParentGuardian"])
    rec = get_or_404(store.families, family_id)
    if role == "ParentGuardian" and rec["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Not your family")
    return object_response(ser.family_out(rec), 200)


# =============================================================================
# Player endpoints
# =============================================================================
def in_registration_window(league):
    now = store.now()
    open_dt = calc.parse_iso(league["registration_open_iso"])
    close_dt = calc.parse_iso(league["registration_close_iso"])
    return open_dt <= now < close_dt


@app.route("/players", methods=["POST"])
def create_player():
    user_id, role = auth(["LeagueAdmin", "ParentGuardian"])
    body = get_json_body()
    require_fields(body, ["league_id", "family_id", "division_id", "full_name", "birth_date"])
    league_id = require_string(body, "league_id")
    family_id = require_string(body, "family_id")
    division_id = require_string(body, "division_id")
    full_name = require_string(body, "full_name")
    birth_date = require_string(body, "birth_date")
    bcr = body.get("birth_certificate_ref")
    if bcr is not None and not isinstance(bcr, str):
        raise err("ERR_INVALID_REQUEST", "birth_certificate_ref must be a string")
    try:
        calc.parse_date(birth_date)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "birth_date must be YYYY-MM-DD")

    # existence (left to right)
    league = find_league(league_id)
    family = get_or_404(store.families, family_id)
    division = get_or_404(store.divisions, division_id)

    # FK scope consistency
    if family["league_id"] != league_id:
        raise err("ERR_FK_SCOPE_MISMATCH", "family not in league")
    if division["league_id"] != league_id:
        raise err("ERR_FK_SCOPE_MISMATCH", "division not in league")

    # ownership for ParentGuardian
    if role == "ParentGuardian" and family_id != user_id:
        raise err("ERR_FORBIDDEN", "Not your family")

    # state: league must be REGISTRATION
    if league["status"] != "REGISTRATION":
        raise err("ERR_INVALID_STATE", "League not in REGISTRATION")

    # registration window
    if not in_registration_window(league):
        raise err("ERR_REGISTRATION_WINDOW_CLOSED", "Registration window closed")

    la = calc.league_age(birth_date, league["age_cutoff_date"])

    rec = base_record()
    rec.update({
        "league_id": league_id,
        "family_id": family_id,
        "division_id": division_id,
        "full_name": full_name,
        "birth_date": birth_date,
        "league_age": la,
        "birth_certificate_ref": bcr,
        "eval_speed": None,
        "eval_hitting": None,
        "eval_fielding": None,
        "eval_score": None,
        "tier": None,
        "team_id": None,
        "status": "REGISTERED",
    })
    store.players[rec["id"]] = rec
    recompute_total_registered(league)
    touch(league)
    return object_response(ser.player_out(rec), 201)


@app.route("/players/<player_id>", methods=["GET"])
def get_player(player_id):
    user_id, role = auth(["LeagueAdmin", "Coach", "ParentGuardian"])
    rec = get_or_404(store.players, player_id)
    if role == "ParentGuardian" and rec["family_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Not your player")
    return object_response(ser.player_out(rec), 200)


@app.route("/players", methods=["GET"])
def list_players():
    user_id, role = auth(["LeagueAdmin", "Coach", "ParentGuardian"])
    items = list(store.players.values())
    for fk in ("league_id", "family_id", "division_id", "team_id"):
        val = request.args.get(fk)
        if val is not None:
            items = [p for p in items if p.get(fk) == val]
    if role == "ParentGuardian":
        items = [p for p in items if p["family_id"] == user_id]
    return list_response(items, ser.player_out)


@app.route("/players/<player_id>/verify-age", methods=["POST"])
def verify_age(player_id):
    auth(["LeagueAdmin"])
    player = get_or_404(store.players, player_id)
    if player["status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", "Player not REGISTERED")
    if player.get("birth_certificate_ref") is None:
        raise err("ERR_INVALID_STATE", "birth_certificate_ref required")
    division = store.divisions.get(player["division_id"])
    la = player["league_age"]
    if division is None or not (division["min_league_age"] <= la <= division["max_league_age"]):
        raise err("ERR_AGE_OUT_OF_RANGE", "league_age out of division range")
    player["status"] = "AGE_VERIFIED"
    touch(player)
    return object_response(ser.player_out(player), 200)


@app.route("/players/<player_id>/evaluate", methods=["POST"])
def evaluate_player(player_id):
    auth(["LeagueAdmin"])
    player = get_or_404(store.players, player_id)
    body = get_json_body()
    require_fields(body, ["eval_speed", "eval_hitting", "eval_fielding"])
    eval_speed = require_int(body, "eval_speed")
    eval_hitting = require_int(body, "eval_hitting")
    eval_fielding = require_int(body, "eval_fielding")
    for v in (eval_speed, eval_hitting, eval_fielding):
        if not (20 <= v <= 80):
            raise err("ERR_INVALID_REQUEST", "eval scores must be in [20,80]")

    league = store.leagues.get(player["league_id"])
    if league is None or league["status"] != "EVALUATION":
        raise err("ERR_INVALID_STATE", "League not in EVALUATION")
    if player["status"] != "AGE_VERIFIED":
        raise err("ERR_INVALID_STATE", "Player not AGE_VERIFIED")

    score, tier = calc.eval_score_and_tier(eval_speed, eval_hitting, eval_fielding)
    player["eval_speed"] = eval_speed
    player["eval_hitting"] = eval_hitting
    player["eval_fielding"] = eval_fielding
    player["eval_score"] = score
    player["tier"] = tier
    player["status"] = "EVALUATED"
    touch(player)
    return object_response(ser.player_out(player), 200)


@app.route("/players/<player_id>/withdraw", methods=["POST"])
def withdraw_player(player_id):
    auth(["LeagueAdmin"])
    player = get_or_404(store.players, player_id)
    league = store.leagues.get(player["league_id"])
    if player["status"] not in ("REGISTERED", "AGE_VERIFIED", "EVALUATED"):
        raise err("ERR_INVALID_STATE", "Player cannot be withdrawn from this state")
    # registration window check (withdrawal is a registration mutation)
    if league is None or league["status"] != "REGISTRATION":
        raise err("ERR_INVALID_STATE", "League not in REGISTRATION")
    if not in_registration_window(league):
        raise err("ERR_REGISTRATION_WINDOW_CLOSED", "Registration window closed")
    if player["status"] == "EVALUATED":
        has_active = any(
            dp["player_id"] == player_id and dp["status"] == "ACTIVE"
            for dp in store.draft_picks.values()
        )
        if has_active:
            raise err("ERR_INVALID_STATE", "Player has an active draft pick")
    player["status"] = "WITHDRAWN"
    touch(player)
    recompute_total_registered(league)
    touch(league)
    return object_response(ser.player_out(player), 200)


# =============================================================================
# Team endpoints
# =============================================================================
@app.route("/teams", methods=["POST"])
def create_team():
    auth(["LeagueAdmin"])
    body = get_json_body()
    require_fields(body, ["league_id", "division_id", "name", "coach_user_id", "draft_slot"])
    league_id = require_string(body, "league_id")
    division_id = require_string(body, "division_id")
    name = require_string(body, "name")
    coach_user_id = require_string(body, "coach_user_id")
    draft_slot = require_int(body, "draft_slot")

    find_league(league_id)
    division = get_or_404(store.divisions, division_id)
    if division["league_id"] != league_id:
        raise err("ERR_FK_SCOPE_MISMATCH", "division not in league")

    rec = base_record()
    rec.update({
        "division_id": division_id,
        "league_id": league_id,
        "name": name,
        "coach_user_id": coach_user_id,
        "draft_slot": draft_slot,
        "roster_count": 0,
        "wins": 0,
        "losses": 0,
        "run_differential": 0,
        "seed": None,
    })
    store.teams[rec["id"]] = rec
    return object_response(ser.team_out(rec), 201)


@app.route("/teams", methods=["GET"])
def list_teams():
    auth(["LeagueAdmin", "Coach", "Referee", "ParentGuardian"])
    items = list(store.teams.values())
    for fk in ("league_id", "division_id"):
        val = request.args.get(fk)
        if val is not None:
            items = [t for t in items if t.get(fk) == val]
    return list_response(items, ser.team_out)


@app.route("/teams/<team_id>", methods=["GET"])
def get_team(team_id):
    auth(["LeagueAdmin", "Coach", "Referee", "ParentGuardian"])
    rec = get_or_404(store.teams, team_id)
    return object_response(ser.team_out(rec), 200)


# =============================================================================
# DraftPick endpoints
# =============================================================================
@app.route("/draft-picks", methods=["POST"])
def create_draft_pick():
    user_id, role = auth(["LeagueAdmin", "Coach"])
    body = get_json_body()
    require_fields(body, ["league_id", "team_id", "player_id", "expected_league_version"])
    league_id = require_string(body, "league_id")
    team_id = require_string(body, "team_id")
    player_id = require_string(body, "player_id")
    expected_version = require_int(body, "expected_league_version")

    # existence left to right
    league = find_league(league_id)
    team = get_or_404(store.teams, team_id)
    player = get_or_404(store.players, player_id)

    # FK scope
    if team["league_id"] != league_id:
        raise err("ERR_FK_SCOPE_MISMATCH", "team not in league")
    if player["league_id"] != league_id:
        raise err("ERR_FK_SCOPE_MISMATCH", "player not in league")

    # ownership for Coach
    if role == "Coach" and team["coach_user_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Not your team")

    # state: league DRAFT, player EVALUATED
    if league["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "League not in DRAFT")
    if player["status"] != "EVALUATED":
        raise err("ERR_INVALID_STATE", "Player not EVALUATED")

    # snake order check (ERR_NOT_YOUR_PICK) — priority 8
    division_id = team["division_id"]
    div_teams = [t for t in store.teams.values() if t["division_id"] == division_id]
    team_count = len(div_teams)
    picks_made = sum(
        1 for dp in store.draft_picks.values()
        if dp["status"] == "ACTIVE" and store.teams.get(dp["team_id"], {}).get("division_id") == division_id
    )
    round_number, expected_slot, overall_number = calc.snake_expected_slot(
        picks_made, team_count, league["draft_snake"]
    )
    if team["draft_slot"] != expected_slot:
        raise err("ERR_NOT_YOUR_PICK", "Not this team's pick")

    # roster cap (ERR_ROSTER_FULL) — priority 14
    division = store.divisions.get(division_id)
    if team["roster_count"] >= division["roster_cap"]:
        raise err("ERR_ROSTER_FULL", "Team roster is full")

    # OCC (ERR_STALE_LEAGUE_VERSION) — priority 17 (after business checks)
    if expected_version != league["version"]:
        raise err("ERR_STALE_LEAGUE_VERSION", "Stale league version")

    # commit
    rec = base_record()
    rec.update({
        "league_id": league_id,
        "team_id": team_id,
        "player_id": player_id,
        "round_number": round_number,
        "overall_number": overall_number,
        "status": "ACTIVE",
    })
    store.draft_picks[rec["id"]] = rec

    player["team_id"] = team_id
    player["status"] = "DRAFTED"
    touch(player)
    team["roster_count"] += 1
    touch(team)
    touch(league)
    return object_response(ser.draft_pick_out(rec), 201)


@app.route("/draft-picks", methods=["GET"])
def list_draft_picks():
    auth(["LeagueAdmin", "Coach"])
    items = list(store.draft_picks.values())
    for fk in ("league_id", "team_id", "player_id"):
        val = request.args.get(fk)
        if val is not None:
            items = [d for d in items if d.get(fk) == val]
    return list_response(items, ser.draft_pick_out)


@app.route("/draft-picks/<pick_id>", methods=["GET"])
def get_draft_pick(pick_id):
    auth(["LeagueAdmin", "Coach"])
    rec = get_or_404(store.draft_picks, pick_id)
    return object_response(ser.draft_pick_out(rec), 200)


@app.route("/draft-picks/<pick_id>/void", methods=["POST"])
def void_draft_pick(pick_id):
    auth(["LeagueAdmin"])
    pick = get_or_404(store.draft_picks, pick_id)
    league = store.leagues.get(pick["league_id"])
    if league is None or league["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "League not in DRAFT")
    if pick["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Pick not ACTIVE")
    # only the most recent ACTIVE pick (highest overall_number) may be voided
    max_overall = max(
        (dp["overall_number"] for dp in store.draft_picks.values()
         if dp["status"] == "ACTIVE"),
        default=None,
    )
    if pick["overall_number"] != max_overall:
        raise err("ERR_NOT_LAST_PICK", "Not the most recent active pick")

    pick["status"] = "VOIDED"
    touch(pick)
    # revert player DRAFTED -> EVALUATED
    player = store.players.get(pick["player_id"])
    if player is not None:
        player["team_id"] = None
        player["status"] = "EVALUATED"
        touch(player)
    team = store.teams.get(pick["team_id"])
    if team is not None:
        team["roster_count"] -= 1
        touch(team)
    touch(league)
    return object_response(ser.draft_pick_out(pick), 200)


# =============================================================================
# Field endpoints
# =============================================================================
@app.route("/fields", methods=["POST"])
def create_field():
    auth(["LeagueAdmin"])
    body = get_json_body()
    require_fields(body, ["league_id", "name"])
    league_id = require_string(body, "league_id")
    name = require_string(body, "name")
    buffer = optional_int(body, "turnover_buffer_minutes", 30)
    find_league(league_id)

    rec = base_record()
    rec.update({
        "league_id": league_id,
        "name": name,
        "turnover_buffer_minutes": buffer,
    })
    store.fields[rec["id"]] = rec
    return object_response(ser.field_out(rec), 201)


@app.route("/fields", methods=["GET"])
def list_fields():
    auth(["LeagueAdmin", "Coach", "Referee", "ParentGuardian"])
    items = list(store.fields.values())
    val = request.args.get("league_id")
    if val is not None:
        items = [f for f in items if f["league_id"] == val]
    return list_response(items, ser.field_out)


@app.route("/fields/<field_id>", methods=["GET"])
def get_field(field_id):
    auth(["LeagueAdmin", "Coach", "Referee", "ParentGuardian"])
    rec = get_or_404(store.fields, field_id)
    return object_response(ser.field_out(rec), 200)


# =============================================================================
# Referee endpoints
# =============================================================================
@app.route("/referees", methods=["POST"])
def create_referee():
    auth(["LeagueAdmin"])
    body = get_json_body()
    require_fields(body, ["league_id", "user_id", "full_name"])
    league_id = require_string(body, "league_id")
    ref_user_id = require_string(body, "user_id")
    full_name = require_string(body, "full_name")
    max_games = optional_int(body, "max_games_per_day", 3)
    find_league(league_id)

    rec = base_record()
    rec.update({
        "league_id": league_id,
        "user_id": ref_user_id,
        "full_name": full_name,
        "max_games_per_day": max_games,
    })
    store.referees[rec["id"]] = rec
    return object_response(ser.referee_out(rec), 201)


@app.route("/referees", methods=["GET"])
def list_referees():
    auth(["LeagueAdmin", "Referee"])
    items = list(store.referees.values())
    val = request.args.get("league_id")
    if val is not None:
        items = [r for r in items if r["league_id"] == val]
    return list_response(items, ser.referee_out)


@app.route("/referees/<referee_id>", methods=["GET"])
def get_referee(referee_id):
    auth(["LeagueAdmin", "Referee"])
    rec = get_or_404(store.referees, referee_id)
    return object_response(ser.referee_out(rec), 200)


# =============================================================================
# Game endpoints
# =============================================================================
def field_slot_conflict(field, start_dt, end_dt, exclude_game_id=None):
    from datetime import timedelta
    buffer = timedelta(minutes=field["turnover_buffer_minutes"])
    for g in store.games.values():
        if g["field_id"] != field["id"]:
            continue
        if exclude_game_id is not None and g["id"] == exclude_game_id:
            continue
        if g["status"] in ("FINAL", "FORFEITED", "RAINED_OUT"):
            continue
        g_start = calc.parse_iso(g["start_iso"])
        g_end = calc.parse_iso(g["end_iso"])
        if start_dt < (g_end + buffer) and (g_start - buffer) < end_dt:
            return True
    return False


@app.route("/games", methods=["POST"])
def create_game():
    auth(["LeagueAdmin"])
    body = get_json_body()
    require_fields(body, [
        "league_id", "division_id", "home_team_id", "away_team_id",
        "field_id", "start_iso", "end_iso",
    ])
    league_id = require_string(body, "league_id")
    division_id = require_string(body, "division_id")
    home_team_id = require_string(body, "home_team_id")
    away_team_id = require_string(body, "away_team_id")
    field_id = require_string(body, "field_id")
    start_iso = require_string(body, "start_iso")
    end_iso = require_string(body, "end_iso")
    game_type = body.get("game_type", "REGULAR")
    validate_enum(game_type, {"REGULAR", "PLAYOFF"}, "game_type")
    playoff_round = body.get("playoff_round")
    if game_type == "PLAYOFF":
        if playoff_round is None:
            raise err("ERR_INVALID_REQUEST", "playoff_round required for PLAYOFF")
        playoff_round = require_int(body, "playoff_round")
    else:
        playoff_round = None
    try:
        start_dt = calc.parse_iso(start_iso)
        end_dt = calc.parse_iso(end_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "start/end must be ISO 8601")

    # existence left to right
    league = find_league(league_id)
    division = get_or_404(store.divisions, division_id)
    home_team = get_or_404(store.teams, home_team_id)
    away_team = get_or_404(store.teams, away_team_id)
    field = get_or_404(store.fields, field_id)

    # FK scope: division in league; both teams in this division; field in league
    if division["league_id"] != league_id:
        raise err("ERR_FK_SCOPE_MISMATCH", "division not in league")
    if home_team["division_id"] != division_id or away_team["division_id"] != division_id:
        raise err("ERR_FK_SCOPE_MISMATCH", "teams not in division")
    if field["league_id"] != league_id:
        raise err("ERR_FK_SCOPE_MISMATCH", "field not in league")

    # field slot conflict
    if field_slot_conflict(field, start_dt, end_dt):
        raise err("ERR_FIELD_SLOT_CONFLICT", "Field slot conflict")

    rec = base_record()
    rec.update({
        "league_id": league_id,
        "division_id": division_id,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "field_id": field_id,
        "start_iso": start_iso,
        "end_iso": end_iso,
        "game_type": game_type,
        "playoff_round": playoff_round,
        "home_runs": None,
        "away_runs": None,
        "winner_team_id": None,
        "rainout_count": 0,
        "status": "SCHEDULED",
    })
    store.games[rec["id"]] = rec
    return object_response(ser.game_out(rec), 201)


@app.route("/games/<game_id>", methods=["GET"])
def get_game(game_id):
    auth(["LeagueAdmin", "Coach", "Referee", "ParentGuardian"])
    rec = get_or_404(store.games, game_id)
    return object_response(ser.game_out(rec), 200)


@app.route("/games", methods=["GET"])
def list_games():
    auth(["LeagueAdmin", "Coach", "Referee", "ParentGuardian"])
    items = list(store.games.values())
    for fk in ("league_id", "field_id", "home_team_id", "away_team_id",
               "division_id", "winner_team_id"):
        val = request.args.get(fk)
        if val is not None:
            items = [g for g in items if g.get(fk) == val]
    return list_response(items, ser.game_out)


@app.route("/games/<game_id>/start", methods=["POST"])
def start_game(game_id):
    auth(["LeagueAdmin"])
    game = get_or_404(store.games, game_id)
    league = store.leagues.get(game["league_id"])
    if league is None or league["status"] not in ("SEASON", "PLAYOFFS"):
        raise err("ERR_INVALID_STATE", "League not in SEASON/PLAYOFFS")
    if game["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Game not SCHEDULED")
    has_ref = any(
        a["game_id"] == game_id and a["status"] in ("CONFIRMED", "CHECKED_IN")
        for a in store.assignments.values()
    )
    if not has_ref:
        raise err("ERR_NO_REFEREE_CONFIRMED", "No confirmed referee")
    game["status"] = "IN_PROGRESS"
    touch(game)
    return object_response(ser.game_out(game), 200)


@app.route("/games/<game_id>/finalize", methods=["POST"])
def finalize_game(game_id):
    auth(["LeagueAdmin"])
    game = get_or_404(store.games, game_id)
    body = get_json_body()
    require_fields(body, ["home_runs", "away_runs"])
    home_runs = require_int(body, "home_runs")
    away_runs = require_int(body, "away_runs")
    if home_runs < 0 or away_runs < 0:
        raise err("ERR_INVALID_REQUEST", "runs must be non-negative")
    if game["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Game not IN_PROGRESS")
    if home_runs == away_runs:
        raise err("ERR_TIE_NOT_ALLOWED", "Ties not allowed")

    home_team = store.teams.get(game["home_team_id"])
    away_team = store.teams.get(game["away_team_id"])
    if home_runs > away_runs:
        winner, loser = home_team, away_team
        game["winner_team_id"] = game["home_team_id"]
    else:
        winner, loser = away_team, home_team
        game["winner_team_id"] = game["away_team_id"]

    game["home_runs"] = home_runs
    game["away_runs"] = away_runs
    game["status"] = "FINAL"
    touch(game)

    # update standings
    if home_team is not None:
        home_team["run_differential"] += (home_runs - away_runs)
        if winner is home_team:
            home_team["wins"] += 1
        else:
            home_team["losses"] += 1
        touch(home_team)
    if away_team is not None:
        away_team["run_differential"] += (away_runs - home_runs)
        if winner is away_team:
            away_team["wins"] += 1
        else:
            away_team["losses"] += 1
        touch(away_team)

    return object_response(ser.game_out(game), 200)


@app.route("/games/<game_id>/rainout", methods=["POST"])
def rainout_game(game_id):
    auth(["LeagueAdmin"])
    game = get_or_404(store.games, game_id)
    league = store.leagues.get(game["league_id"])
    if league is None or league["status"] not in ("SEASON", "PLAYOFFS"):
        raise err("ERR_INVALID_STATE", "League not in SEASON/PLAYOFFS")
    if game["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Game not SCHEDULED")
    game["status"] = "RAINED_OUT"
    touch(game)
    # release PROPOSED/CONFIRMED assignments
    for a in store.assignments.values():
        if a["game_id"] == game_id and a["status"] in ("PROPOSED", "CONFIRMED"):
            a["status"] = "RELEASED"
            touch(a)
    return object_response(ser.game_out(game), 200)


@app.route("/games/<game_id>/reschedule", methods=["POST"])
def reschedule_game(game_id):
    auth(["LeagueAdmin"])
    game = get_or_404(store.games, game_id)
    body = get_json_body()
    require_fields(body, ["start_iso", "end_iso", "expected_game_version"])
    start_iso = require_string(body, "start_iso")
    end_iso = require_string(body, "end_iso")
    expected_version = require_int(body, "expected_game_version")
    try:
        start_dt = calc.parse_iso(start_iso)
        end_dt = calc.parse_iso(end_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "start/end must be ISO 8601")

    if game["status"] != "RAINED_OUT":
        raise err("ERR_INVALID_STATE", "Game not RAINED_OUT")

    # field slot conflict (priority 12, before OCC priority 17)
    field = store.fields.get(game["field_id"])
    if field is not None and field_slot_conflict(field, start_dt, end_dt, exclude_game_id=game_id):
        raise err("ERR_FIELD_SLOT_CONFLICT", "Field slot conflict")

    # OCC
    if expected_version != game["version"]:
        raise err("ERR_STALE_GAME_VERSION", "Stale game version")

    game["start_iso"] = start_iso
    game["end_iso"] = end_iso
    game["rainout_count"] += 1
    game["status"] = "SCHEDULED"
    touch(game)
    return object_response(ser.game_out(game), 200)


@app.route("/games/<game_id>/forfeit", methods=["POST"])
def forfeit_game(game_id):
    auth(["LeagueAdmin"])
    game = get_or_404(store.games, game_id)
    body = get_json_body()
    require_fields(body, ["forfeiting_team_id"])
    forfeiting_team_id = require_string(body, "forfeiting_team_id")
    if game["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Game not SCHEDULED")
    if forfeiting_team_id not in (game["home_team_id"], game["away_team_id"]):
        raise err("ERR_INVALID_REQUEST", "forfeiting_team_id not in game")

    if forfeiting_team_id == game["home_team_id"]:
        winner_id = game["away_team_id"]
    else:
        winner_id = game["home_team_id"]
    game["winner_team_id"] = winner_id
    game["status"] = "FORFEITED"
    touch(game)

    winner = store.teams.get(winner_id)
    loser = store.teams.get(forfeiting_team_id)
    if winner is not None:
        winner["wins"] += 1
        touch(winner)
    if loser is not None:
        loser["losses"] += 1
        touch(loser)

    # release non-terminal assignments
    for a in store.assignments.values():
        if a["game_id"] == game_id and a["status"] in ("PROPOSED", "CONFIRMED", "CHECKED_IN"):
            a["status"] = "RELEASED"
            touch(a)

    return object_response(ser.game_out(game), 200)


# =============================================================================
# RefereeAssignment endpoints
# =============================================================================
@app.route("/assignments", methods=["POST"])
def create_assignment():
    auth(["LeagueAdmin"])
    body = get_json_body()
    require_fields(body, ["game_id", "referee_id"])
    game_id = require_string(body, "game_id")
    referee_id = require_string(body, "referee_id")
    role_val = body.get("role", "PLATE")
    validate_enum(role_val, {"PLATE", "BASE"}, "role")

    game = get_or_404(store.games, game_id)
    referee = get_or_404(store.referees, referee_id)
    # FK scope: referee in same league as game
    if referee["league_id"] != game["league_id"]:
        raise err("ERR_FK_SCOPE_MISMATCH", "referee not in game's league")

    rec = base_record()
    rec.update({
        "game_id": game_id,
        "referee_id": referee_id,
        "role": role_val,
        "status": "PROPOSED",
    })
    store.assignments[rec["id"]] = rec
    return object_response(ser.assignment_out(rec), 201)


@app.route("/assignments", methods=["GET"])
def list_assignments():
    auth(["LeagueAdmin", "Referee"])
    items = list(store.assignments.values())
    for fk in ("game_id", "referee_id"):
        val = request.args.get(fk)
        if val is not None:
            items = [a for a in items if a.get(fk) == val]
    return list_response(items, ser.assignment_out)


@app.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    auth(["LeagueAdmin", "Referee"])
    rec = get_or_404(store.assignments, assignment_id)
    return object_response(ser.assignment_out(rec), 200)


def assert_assignment_owner(assignment, user_id):
    referee = store.referees.get(assignment["referee_id"])
    if referee is None or referee["user_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Not your assignment")


@app.route("/assignments/<assignment_id>/confirm", methods=["POST"])
def confirm_assignment(assignment_id):
    user_id, role = auth(["Referee"])
    assignment = get_or_404(store.assignments, assignment_id)
    assert_assignment_owner(assignment, user_id)
    if assignment["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Assignment not PROPOSED")

    game = store.games.get(assignment["game_id"])
    referee = store.referees.get(assignment["referee_id"])
    this_start = calc.parse_iso(game["start_iso"])
    this_end = calc.parse_iso(game["end_iso"])

    # time-overlap check (priority 11, before day-limit priority 13)
    for a in store.assignments.values():
        if a["id"] == assignment_id:
            continue
        if a["referee_id"] != referee["id"]:
            continue
        if a["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        other_game = store.games.get(a["game_id"])
        if other_game is None:
            continue
        o_start = calc.parse_iso(other_game["start_iso"])
        o_end = calc.parse_iso(other_game["end_iso"])
        if calc.intervals_overlap(this_start, this_end, o_start, o_end):
            raise err("ERR_REFEREE_TIME_CONFLICT", "Referee time conflict")

    # day-limit check (priority 13)
    this_day = this_start.date()
    same_day_count = 0
    for a in store.assignments.values():
        if a["id"] == assignment_id:
            continue
        if a["referee_id"] != referee["id"]:
            continue
        if a["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        other_game = store.games.get(a["game_id"])
        if other_game is None:
            continue
        if calc.parse_iso(other_game["start_iso"]).date() == this_day:
            same_day_count += 1
    if same_day_count >= referee["max_games_per_day"]:
        raise err("ERR_REFEREE_DAY_LIMIT", "Referee day limit reached")

    assignment["status"] = "CONFIRMED"
    touch(assignment)
    return object_response(ser.assignment_out(assignment), 200)


@app.route("/assignments/<assignment_id>/decline", methods=["POST"])
def decline_assignment(assignment_id):
    user_id, role = auth(["Referee"])
    assignment = get_or_404(store.assignments, assignment_id)
    assert_assignment_owner(assignment, user_id)
    if assignment["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Assignment not PROPOSED")
    assignment["status"] = "DECLINED"
    touch(assignment)
    return object_response(ser.assignment_out(assignment), 200)


@app.route("/assignments/<assignment_id>/check-in", methods=["POST"])
def check_in_assignment(assignment_id):
    user_id, role = auth(["Referee"])
    assignment = get_or_404(store.assignments, assignment_id)
    assert_assignment_owner(assignment, user_id)
    if assignment["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Assignment not CONFIRMED")
    game = store.games.get(assignment["game_id"])
    if game is None or game["status"] not in ("IN_PROGRESS", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Game not IN_PROGRESS/SCHEDULED")
    assignment["status"] = "CHECKED_IN"
    touch(assignment)
    return object_response(ser.assignment_out(assignment), 200)


@app.route("/assignments/<assignment_id>/release", methods=["POST"])
def release_assignment(assignment_id):
    auth(["LeagueAdmin"])
    assignment = get_or_404(store.assignments, assignment_id)
    if assignment["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Assignment not CONFIRMED")
    assignment["status"] = "RELEASED"
    touch(assignment)
    return object_response(ser.assignment_out(assignment), 200)


# =============================================================================
# VolunteerCommitment endpoints
# =============================================================================
@app.route("/volunteer-commitments", methods=["POST"])
def create_commitment():
    user_id, role = auth(["LeagueAdmin", "ParentGuardian"])
    body = get_json_body()
    require_fields(body, ["game_id", "family_id", "role", "credit_cents"])
    game_id = require_string(body, "game_id")
    family_id = require_string(body, "family_id")
    role_val = require_string(body, "role")
    validate_enum(role_val, {"SCOREKEEPER", "CONCESSIONS", "FIELD_PREP"}, "role")
    credit_cents = require_int(body, "credit_cents")

    game = get_or_404(store.games, game_id)
    family = get_or_404(store.families, family_id)

    if role == "ParentGuardian" and family_id != user_id:
        raise err("ERR_FORBIDDEN", "Not your family")

    rec = base_record()
    rec.update({
        "game_id": game_id,
        "family_id": family_id,
        "role": role_val,
        "credit_cents": credit_cents,
        "status": "PLEDGED",
    })
    store.volunteer_commitments[rec["id"]] = rec
    return object_response(ser.commitment_out(rec), 201)


@app.route("/volunteer-commitments", methods=["GET"])
def list_commitments():
    user_id, role = auth(["LeagueAdmin", "ParentGuardian"])
    items = list(store.volunteer_commitments.values())
    for fk in ("game_id", "family_id"):
        val = request.args.get(fk)
        if val is not None:
            items = [c for c in items if c.get(fk) == val]
    if role == "ParentGuardian":
        items = [c for c in items if c["family_id"] == user_id]
    return list_response(items, ser.commitment_out)


@app.route("/volunteer-commitments/<commitment_id>", methods=["GET"])
def get_commitment(commitment_id):
    user_id, role = auth(["LeagueAdmin", "ParentGuardian"])
    rec = get_or_404(store.volunteer_commitments, commitment_id)
    if role == "ParentGuardian" and rec["family_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Not your commitment")
    return object_response(ser.commitment_out(rec), 200)


@app.route("/volunteer-commitments/<commitment_id>/fulfill", methods=["POST"])
def fulfill_commitment(commitment_id):
    auth(["LeagueAdmin"])
    commitment = get_or_404(store.volunteer_commitments, commitment_id)
    if commitment["status"] != "PLEDGED":
        raise err("ERR_INVALID_STATE", "Commitment not PLEDGED")
    game = store.games.get(commitment["game_id"])
    if game is None or game["status"] != "FINAL":
        raise err("ERR_INVALID_STATE", "Game not FINAL")
    commitment["status"] = "FULFILLED"
    touch(commitment)
    family = store.families.get(commitment["family_id"])
    if family is not None:
        proposed = family["volunteer_credit_cents"] + commitment["credit_cents"]
        family["volunteer_credit_cents"] = min(proposed, family["volunteer_deposit_cents"])
        touch(family)
    return object_response(ser.commitment_out(commitment), 200)


@app.route("/volunteer-commitments/<commitment_id>/mark-no-show", methods=["POST"])
def mark_no_show_commitment(commitment_id):
    auth(["LeagueAdmin"])
    commitment = get_or_404(store.volunteer_commitments, commitment_id)
    if commitment["status"] != "PLEDGED":
        raise err("ERR_INVALID_STATE", "Commitment not PLEDGED")
    game = store.games.get(commitment["game_id"])
    if game is None or game["status"] != "FINAL":
        raise err("ERR_INVALID_STATE", "Game not FINAL")
    commitment["status"] = "NO_SHOW"
    touch(commitment)
    return object_response(ser.commitment_out(commitment), 200)


# =============================================================================
# List response helper (sort by created_at ASC, paginate)
# =============================================================================
def list_response(items, serializer):
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    limit, offset = paginate()
    page = apply_pagination(items, limit, offset)
    return array_response([serializer(r) for r in page], limit, offset, total, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
