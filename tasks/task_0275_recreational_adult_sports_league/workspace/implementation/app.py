"""Recreational Adult Sports League API — Flask implementation.

In-memory only; the store is wiped on every process boot. No seeding.
"""
import os
from datetime import datetime, timezone

from flask import Flask, request

import errors as E
from errors import ApiError, err
from response import success, list_response, error_response
from store import db, now_iso, new_id

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Roles & enums
# ---------------------------------------------------------------------------
ROLES = {"LeagueAdmin", "TeamCaptain", "Referee", "ConductOfficer"}

SPORTS = {"SOCCER", "BASKETBALL", "SOFTBALL", "VOLLEYBALL"}
SKILL_TIERS = {"REC", "INTERMEDIATE", "COMPETITIVE"}
TIEBREAKERS = {"HEAD_TO_HEAD", "POINT_DIFFERENTIAL"}
GAME_STAGES = {"REGULAR", "PLAYOFF"}
ASSIGN_ROLES = {"HEAD", "ASSISTANT", "SCOREKEEPER"}
SEVERITIES = {"WARNING", "YELLOW", "RED", "ABUSE"}
SEVERITY_POINTS = {"WARNING": 1, "YELLOW": 2, "RED": 4, "ABUSE": 8}

WIN_POINTS = 3
DRAW_POINTS = 1
LOSS_POINTS = 0
FORFEIT_WIN_SCORE = 3

WARN_THRESHOLD = 3
SUSPEND_THRESHOLD = 6
BAN_THRESHOLD = 12
SUSPENSION_GAMES = 2


# ---------------------------------------------------------------------------
# Auth context
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_ctx():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(E.ERR_UNAUTHENTICATED, "Missing or unknown authentication headers")
    return Ctx(user_id, role)


def require_role(ctx, *allowed):
    if ctx.role not in allowed:
        raise err(E.ERR_FORBIDDEN, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO8601 instant into an aware UTC datetime. None on failure."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------
def touch(record):
    """Bump updated_at + version for a full-lifecycle entity."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def base_record(extra=None):
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


# ---------------------------------------------------------------------------
# Serialization (strip internal fields)
# ---------------------------------------------------------------------------
def _strip(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ser_season(s):
    return {
        "id": s["id"], "name": s["name"], "sport": s["sport"],
        "registration_opens_at": s["registration_opens_at"],
        "registration_closes_at": s["registration_closes_at"],
        "registration_status": s["registration_status"],
        "refund_full_cutoff_at": s["refund_full_cutoff_at"],
        "refund_partial_pct": s["refund_partial_pct"],
        "clock_now": s["clock_now"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_division(d):
    return {
        "id": d["id"], "season_id": d["season_id"], "name": d["name"],
        "skill_tier": d["skill_tier"],
        "min_roster_size": d["min_roster_size"],
        "max_roster_size": d["max_roster_size"],
        "team_capacity": d["team_capacity"],
        "registration_fee_cents": d["registration_fee_cents"],
        "confirmed_team_count": compute_confirmed_count(d["id"]),
        "standings_tiebreaker": d["standings_tiebreaker"],
        "created_at": d["created_at"], "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_team(t):
    st = team_standings(t["id"])
    return {
        "id": t["id"], "division_id": t["division_id"],
        "captain_player_id": t["captain_player_id"], "name": t["name"],
        "status": t["status"],
        "roster_size": compute_roster_size(t["id"]),
        "fee_charged_cents": compute_fee_charged(t["id"]),
        "refund_issued_cents": compute_refund_issued(t["id"]),
        "wins": st["wins"], "losses": st["losses"], "draws": st["draws"],
        "points": st["points"],
        "points_for": st["points_for"], "points_against": st["points_against"],
        "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_player(p):
    return {
        "id": p["id"], "full_name": p["full_name"], "email": p["email"],
        "is_free_agent": compute_is_free_agent(p["id"]),
        "conduct_points": p["conduct_points"],
        "suspension_status": p["suspension_status"],
        "suspended_until_game_index": p["suspended_until_game_index"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_roster_entry(r):
    team = db.teams.get(r["team_id"])
    is_captain = bool(team and r["player_id"] == team["captain_player_id"])
    return {
        "id": r["id"], "team_id": r["team_id"], "player_id": r["player_id"],
        "state": r["state"], "is_captain": is_captain,
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_venue(v):
    return {
        "id": v["id"], "name": v["name"], "field_count": v["field_count"],
        "turnover_buffer_minutes": v["turnover_buffer_minutes"],
        "created_at": v["created_at"], "updated_at": v["updated_at"],
        "version": v["version"],
    }


def ser_referee(r):
    return {
        "id": r["id"], "full_name": r["full_name"],
        "certified_sports": r["certified_sports"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_game(g):
    return {
        "id": g["id"], "division_id": g["division_id"],
        "home_team_id": g["home_team_id"], "away_team_id": g["away_team_id"],
        "venue_id": g["venue_id"], "field_index": g["field_index"],
        "round_index": g["round_index"], "stage": g["stage"],
        "starts_at": g["starts_at"], "ends_at": g["ends_at"],
        "schedule_status": g["schedule_status"],
        "score_status": g["score_status"],
        "home_score": g["home_score"], "away_score": g["away_score"],
        "forfeiting_team_id": g["forfeiting_team_id"],
        "created_at": g["created_at"], "updated_at": g["updated_at"],
        "version": g["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"], "game_id": a["game_id"], "referee_id": a["referee_id"],
        "role": a["role"], "state": a["state"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"], "team_id": p["team_id"], "kind": p["kind"],
        "amount_cents": p["amount_cents"], "status": p["status"],
        "reason": p["reason"], "created_at": p["created_at"],
    }


def ser_report(r):
    return {
        "id": r["id"], "game_id": r["game_id"], "player_id": r["player_id"],
        "severity": r["severity"], "status": r["status"],
        "points": r["points"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "version": r["version"],
    }


# ---------------------------------------------------------------------------
# Computed-value helpers
# ---------------------------------------------------------------------------
def compute_confirmed_count(division_id):
    return sum(
        1 for t in db.teams.values()
        if t["division_id"] == division_id
        and t["status"] in ("CONFIRMED", "WITHDRAWN_LOCKED")
    )


def compute_roster_size(team_id):
    return sum(
        1 for r in db.roster_entries.values()
        if r["team_id"] == team_id and r["state"] == "ACTIVE"
    )


def compute_fee_charged(team_id):
    return sum(
        p["amount_cents"] for p in db.payments.values()
        if p["team_id"] == team_id and p["kind"] == "FEE"
        and p["status"] == "CAPTURED"
    )


def compute_refund_issued(team_id):
    return sum(
        p["amount_cents"] for p in db.payments.values()
        if p["team_id"] == team_id and p["kind"] == "REFUND"
        and p["status"] == "CAPTURED"
    )


def compute_is_free_agent(player_id):
    return not any(
        r["player_id"] == player_id and r["state"] == "ACTIVE"
        for r in db.roster_entries.values()
    )


def settled_games_for_team(team_id):
    """REGULAR games in the team's division that count toward standings."""
    out = []
    for g in db.games.values():
        if g["stage"] != "REGULAR":
            continue
        if team_id not in (g["home_team_id"], g["away_team_id"]):
            continue
        if g["score_status"] == "CONFIRMED" or g["schedule_status"] == "FORFEITED":
            out.append(g)
    return out


def team_scores_in_game(team_id, g):
    """Return (own_score, opp_score) for standings, honoring forfeits."""
    if g["schedule_status"] == "FORFEITED":
        ft = g.get("forfeiting_team_id")
        if ft == team_id:
            return (0, FORFEIT_WIN_SCORE)
        else:
            return (FORFEIT_WIN_SCORE, 0)
    if g["home_team_id"] == team_id:
        return (g["home_score"], g["away_score"])
    return (g["away_score"], g["home_score"])


def team_standings(team_id):
    wins = losses = draws = pf = pa = 0
    for g in settled_games_for_team(team_id):
        own, opp = team_scores_in_game(team_id, g)
        if own is None or opp is None:
            continue
        pf += own
        pa += opp
        if own > opp:
            wins += 1
        elif own < opp:
            losses += 1
        else:
            draws += 1
    points = wins * WIN_POINTS + draws * DRAW_POINTS + losses * LOSS_POINTS
    return {
        "wins": wins, "losses": losses, "draws": draws, "points": points,
        "points_for": pf, "points_against": pa,
    }


def recompute_player_suspension(player, triggering_round_index=None):
    """Recompute conduct_points + suspension from UPHELD/APPEALED reports."""
    pts = 0
    for r in db.conduct_reports.values():
        if r["player_id"] == player["id"] and r["status"] in ("UPHELD", "APPEALED"):
            pts += SEVERITY_POINTS[r["severity"]]
    player["conduct_points"] = pts
    if pts >= BAN_THRESHOLD:
        player["suspension_status"] = "BANNED"
        player["suspended_until_game_index"] = 9999
    elif pts >= SUSPEND_THRESHOLD:
        player["suspension_status"] = "SUSPENDED"
        base = (triggering_round_index + SUSPENSION_GAMES) if triggering_round_index else 0
        player["suspended_until_game_index"] = max(
            player.get("suspended_until_game_index", 0), base
        )
    elif pts >= WARN_THRESHOLD:
        player["suspension_status"] = "WARNED"
        # suspended_until_game_index unchanged
    else:
        player["suspension_status"] = "CLEAR"
        player["suspended_until_game_index"] = 0


# ---------------------------------------------------------------------------
# Lookup helpers (raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def get_or_404(coll, _id):
    rec = coll.get(_id)
    if rec is None:
        raise err(E.ERR_NOT_FOUND, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Body / input helpers
# ---------------------------------------------------------------------------
def get_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(E.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(E.ERR_INVALID_REQUEST, f"Missing required field: {f}")


def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(E.ERR_PAGINATION_RANGE, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(E.ERR_PAGINATION_RANGE, "limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(E.ERR_PAGINATION_RANGE, "offset must be an integer")
        if offset < 0:
            raise err(E.ERR_PAGINATION_RANGE, "offset must be >= 0")
    return limit, offset


def paginate_and_respond(records, serializer):
    limit, offset = parse_pagination()
    records = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(records)
    page = records[offset:offset + limit]
    return list_response([serializer(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Clock helper
# ---------------------------------------------------------------------------
def season_clock(season):
    return parse_dt(season["clock_now"])


def season_of_division(division):
    return db.seasons.get(division["season_id"])


def division_of_team(team):
    return db.divisions.get(team["division_id"])


def season_of_team(team):
    div = division_of_team(team)
    return season_of_division(div) if div else None


def division_of_game(game):
    return db.divisions.get(game["division_id"])


def season_of_game(game):
    div = division_of_game(game)
    return season_of_division(div) if div else None


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    resp = error_response(e.error_id, e.message)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    resp = error_response("ERR_NOT_FOUND", "Resource not found")
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    resp = error_response("ERR_NOT_FOUND", "Method not allowed")
    resp.status_code = 404
    return resp


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    resp = error_response("ERR_INTERNAL", str(e))
    resp.status_code = 500
    return resp


# ===========================================================================
# SEASONS
# ===========================================================================
@app.route("/seasons", methods=["POST"])
def create_season():
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    body = get_json()
    require_fields(body, "name", "sport", "registration_opens_at",
                   "registration_closes_at", "refund_full_cutoff_at")
    if body["sport"] not in SPORTS:
        raise err(E.ERR_INVALID_REQUEST, "Invalid sport")
    opens = parse_dt(body["registration_opens_at"])
    closes = parse_dt(body["registration_closes_at"])
    cutoff = parse_dt(body["refund_full_cutoff_at"])
    if opens is None or closes is None or cutoff is None:
        raise err(E.ERR_INVALID_REQUEST, "Invalid datetime")
    if not (closes > opens):
        raise err(E.ERR_INVALID_REQUEST, "registration_closes_at must be after registration_opens_at")
    pct = body.get("refund_partial_pct", 50)
    if pct is None:
        pct = 50
    if not isinstance(pct, int) or isinstance(pct, bool) or pct < 0 or pct > 100:
        raise err(E.ERR_INVALID_REQUEST, "refund_partial_pct must be an integer 0..100")
    rec = base_record({
        "name": body["name"],
        "sport": body["sport"],
        "registration_opens_at": body["registration_opens_at"],
        "registration_closes_at": body["registration_closes_at"],
        "registration_status": "DRAFT",
        "refund_full_cutoff_at": body["refund_full_cutoff_at"],
        "refund_partial_pct": pct,
        "clock_now": None,
    })
    rec["clock_now"] = rec["created_at"]
    db.seasons[rec["id"]] = rec
    return success(ser_season(rec), status=201)


@app.route("/seasons/<sid>", methods=["GET"])
def get_season(sid):
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    s = get_or_404(db.seasons, sid)
    return success(ser_season(s))


@app.route("/seasons/<sid>/transition", methods=["POST"])
def transition_season(sid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    s = get_or_404(db.seasons, sid)
    body = get_json()
    require_fields(body, "target", "expected_season_version")
    target = body["target"]
    valid_targets = {"OPEN", "CLOSED", "SCHEDULED", "IN_PLAY", "PLAYOFFS", "COMPLETE"}
    if target not in valid_targets:
        raise err(E.ERR_INVALID_REQUEST, "Invalid target")
    expected = body["expected_season_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(E.ERR_INVALID_REQUEST, "expected_season_version must be an integer")
    if expected != s["version"]:
        raise err(E.ERR_STALE_VERSION, "Stale season version")
    force = bool(body.get("force", False))

    cur = s["registration_status"]
    # Map valid source state for each target.
    expected_from = {
        "OPEN": "DRAFT", "CLOSED": "OPEN", "SCHEDULED": "CLOSED",
        "IN_PLAY": "SCHEDULED", "PLAYOFFS": "IN_PLAY", "COMPLETE": "PLAYOFFS",
    }
    if cur != expected_from[target]:
        raise err(E.ERR_INVALID_STATE, f"Cannot transition from {cur} to {target}")

    clock = season_clock(s)
    if target == "OPEN":
        if clock < parse_dt(s["registration_opens_at"]):
            raise err(E.ERR_SEASON_PHASE, "Registration window has not opened")
        if not any(d["season_id"] == sid for d in db.divisions.values()):
            raise err(E.ERR_SCHEDULE_INCOMPLETE, "No division exists under the season")
        s["registration_status"] = "OPEN"
    elif target == "CLOSED":
        if not force and clock < parse_dt(s["registration_closes_at"]):
            raise err(E.ERR_SEASON_PHASE, "Registration window has not closed")
        s["registration_status"] = "CLOSED"
        _closing_cascade(sid)
    elif target == "SCHEDULED":
        _check_can_schedule(sid)
        s["registration_status"] = "SCHEDULED"
    elif target == "IN_PLAY":
        earliest = _earliest_game_start(sid)
        if earliest is None:
            raise err(E.ERR_SEASON_PHASE, "No games scheduled")
        if clock < earliest:
            raise err(E.ERR_SEASON_PHASE, "Clock has not reached the earliest game start")
        s["registration_status"] = "IN_PLAY"
        _inplay_cascade(sid)
    elif target == "PLAYOFFS":
        _check_can_playoffs(sid)
        s["registration_status"] = "PLAYOFFS"
        _playoffs_cascade(sid)
    elif target == "COMPLETE":
        _check_can_complete(sid)
        s["registration_status"] = "COMPLETE"

    touch(s)
    return success(ser_season(s))


def _closing_cascade(sid):
    """OPEN->CLOSED settlement: promote/waitlist/cancel PENDING teams."""
    for div in db.divisions.values():
        if div["season_id"] != sid:
            continue
        pending = [
            t for t in db.teams.values()
            if t["division_id"] == div["id"] and t["status"] == "PENDING"
        ]
        pending.sort(key=lambda t: (t["created_at"], t["_seq"]))
        for t in pending:
            if compute_roster_size(t["id"]) >= div["min_roster_size"]:
                if compute_confirmed_count(div["id"]) < div["team_capacity"]:
                    t["status"] = "CONFIRMED"
                    touch(t)
                    touch(div)
                else:
                    t["status"] = "WAITLISTED"
                    touch(t)
            else:
                # Below minimum -> CANCELLED with full refund cascade.
                _cancel_team_with_refund(t)


def _cancel_team_with_refund(team):
    """CLOSED cascade: cancel a sub-minimum PENDING team; full refund if paid."""
    refund_amt, reason = compute_refund(team, force_full=True)
    if refund_amt > 0:
        _write_payment(team["id"], "REFUND", refund_amt, reason)
    elif reason == "FULL_WITHDRAWAL" and compute_fee_charged(team["id"]) == 0:
        pass  # nothing captured; no audit row needed for a never-paid team
    team["status"] = "CANCELLED"
    _release_team_rosters(team)
    touch(team)


def _release_team_rosters(team):
    for r in db.roster_entries.values():
        if r["team_id"] == team["id"] and r["state"] == "ACTIVE":
            r["state"] = "RELEASED"
            touch(r)


def _check_can_schedule(sid):
    divs = [d for d in db.divisions.values() if d["season_id"] == sid]
    for d in divs:
        if compute_confirmed_count(d["id"]) < 2:
            raise err(E.ERR_SCHEDULE_INCOMPLETE, "A division has fewer than 2 confirmed teams")
    for g in db.games.values():
        if season_of_game(g) and season_of_game(g)["id"] == sid and g["stage"] == "REGULAR":
            if g["schedule_status"] != "SCHEDULED":
                raise err(E.ERR_SCHEDULE_INCOMPLETE, "A regular game is not scheduled")
            if not g["venue_id"] or not g["field_index"]:
                raise err(E.ERR_SCHEDULE_INCOMPLETE, "A regular game lacks venue/field")
            has_head = any(
                a["game_id"] == g["id"] and a["role"] == "HEAD"
                and a["state"] == "ASSIGNED"
                for a in db.referee_assignments.values()
            )
            if not has_head:
                raise err(E.ERR_SCHEDULE_INCOMPLETE, "A regular game lacks a HEAD referee")


def _earliest_game_start(sid):
    starts = []
    for g in db.games.values():
        s = season_of_game(g)
        if s and s["id"] == sid:
            dt = parse_dt(g["starts_at"])
            if dt:
                starts.append(dt)
    return min(starts) if starts else None


def _inplay_cascade(sid):
    for t in db.teams.values():
        if t["status"] == "WITHDRAWN_LOCKED":
            s = season_of_team(t)
            if s and s["id"] == sid:
                t["status"] = "WITHDRAWN"
                touch(t)


def _check_can_playoffs(sid):
    for g in db.games.values():
        s = season_of_game(g)
        if not (s and s["id"] == sid):
            continue
        if g["stage"] != "REGULAR":
            continue
        settled = (
            g["score_status"] == "CONFIRMED"
            or g["schedule_status"] == "FORFEITED"
            or g["schedule_status"] == "CANCELLED"
        )
        if not settled:
            raise err(E.ERR_SCHEDULE_INCOMPLETE, "A regular game has not reached a settled result")


def _check_can_complete(sid):
    for g in db.games.values():
        s = season_of_game(g)
        if not (s and s["id"] == sid):
            continue
        if g["stage"] != "PLAYOFF":
            continue
        settled = (g["score_status"] == "CONFIRMED" or g["schedule_status"] == "FORFEITED")
        if not settled:
            raise err(E.ERR_SCHEDULE_INCOMPLETE, "A playoff game is not settled")


def _playoffs_cascade(sid):
    """Per division, seed CONFIRMED teams and generate first-round PLAYOFF games."""
    for div in db.divisions.values():
        if div["season_id"] != sid:
            continue
        seeded = compute_seeded_teams(div)
        n = len(seeded)
        if n < 2:
            continue
        # Pair seed N vs seed (count+1-N) for the first round.
        for i in range(n // 2):
            home = seeded[i]
            away = seeded[n - 1 - i]
            rec = base_record({
                "division_id": div["id"],
                "home_team_id": home["id"],
                "away_team_id": away["id"],
                "venue_id": None,
                "field_index": None,
                "round_index": 1,
                "stage": "PLAYOFF",
                "starts_at": None,
                "ends_at": None,
                "schedule_status": "SCHEDULED",
                "score_status": "PENDING",
                "home_score": None,
                "away_score": None,
                "forfeiting_team_id": None,
            })
            db.games[rec["id"]] = rec


def head_to_head_points(team_id, tied_ids):
    """League points earned in REGULAR settled games strictly among tied teams."""
    pts = 0
    tied = set(tied_ids)
    for g in settled_games_for_team(team_id):
        opp = g["away_team_id"] if g["home_team_id"] == team_id else g["home_team_id"]
        if opp not in tied:
            continue
        own, o = team_scores_in_game(team_id, g)
        if own is None or o is None:
            continue
        if own > o:
            pts += WIN_POINTS
        elif own == o:
            pts += DRAW_POINTS
    return pts


def compute_seeded_teams(div):
    teams = [
        t for t in db.teams.values()
        if t["division_id"] == div["id"] and t["status"] == "CONFIRMED"
    ]
    standings = {t["id"]: team_standings(t["id"]) for t in teams}

    def goal_diff(tid):
        st = standings[tid]
        return st["points_for"] - st["points_against"]

    # Determine tied groups by points for head-to-head computation.
    def sort_key(t):
        tid = t["id"]
        st = standings[tid]
        # tied set = all teams with same points
        tied_ids = [x["id"] for x in teams if standings[x["id"]]["points"] == st["points"]]
        h2h = head_to_head_points(tid, tied_ids)
        gd = goal_diff(tid)
        if div["standings_tiebreaker"] == "HEAD_TO_HEAD":
            return (
                -st["points"], -h2h, -gd, -st["points_for"],
                t["created_at"], t["_seq"],
            )
        else:  # POINT_DIFFERENTIAL
            return (
                -st["points"], -gd, -st["points_for"], -h2h,
                t["created_at"], t["_seq"],
            )

    return sorted(teams, key=sort_key)


# ===========================================================================
# DIVISIONS
# ===========================================================================
@app.route("/seasons/<sid>/divisions", methods=["POST"])
def create_division(sid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    s = get_or_404(db.seasons, sid)
    body = get_json()
    require_fields(body, "name", "skill_tier", "min_roster_size",
                   "max_roster_size", "team_capacity", "registration_fee_cents")
    if body["skill_tier"] not in SKILL_TIERS:
        raise err(E.ERR_INVALID_REQUEST, "Invalid skill_tier")
    tb = body.get("standings_tiebreaker", "HEAD_TO_HEAD")
    if tb is None:
        tb = "HEAD_TO_HEAD"
    if tb not in TIEBREAKERS:
        raise err(E.ERR_INVALID_REQUEST, "Invalid standings_tiebreaker")
    for f in ("min_roster_size", "max_roster_size", "team_capacity", "registration_fee_cents"):
        v = body[f]
        if not isinstance(v, int) or isinstance(v, bool):
            raise err(E.ERR_INVALID_REQUEST, f"{f} must be an integer")
    if body["min_roster_size"] < 1:
        raise err(E.ERR_INVALID_REQUEST, "min_roster_size must be >= 1")
    if body["max_roster_size"] < body["min_roster_size"]:
        raise err(E.ERR_INVALID_REQUEST, "max_roster_size must be >= min_roster_size")
    if body["team_capacity"] < 2:
        raise err(E.ERR_INVALID_REQUEST, "team_capacity must be >= 2")
    if body["registration_fee_cents"] < 0:
        raise err(E.ERR_INVALID_REQUEST, "registration_fee_cents must be >= 0")
    rec = base_record({
        "season_id": sid,
        "name": body["name"],
        "skill_tier": body["skill_tier"],
        "min_roster_size": body["min_roster_size"],
        "max_roster_size": body["max_roster_size"],
        "team_capacity": body["team_capacity"],
        "registration_fee_cents": body["registration_fee_cents"],
        "standings_tiebreaker": tb,
    })
    db.divisions[rec["id"]] = rec
    return success(ser_division(rec), status=201)


@app.route("/seasons/<sid>/divisions", methods=["GET"])
def list_divisions(sid):
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    get_or_404(db.seasons, sid)
    skill_tier = request.args.get("skill_tier")
    recs = [d for d in db.divisions.values() if d["season_id"] == sid]
    if skill_tier:
        recs = [d for d in recs if d["skill_tier"] == skill_tier]
    return paginate_and_respond(recs, ser_division)


@app.route("/divisions/<did>", methods=["GET"])
def get_division(did):
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    d = get_or_404(db.divisions, did)
    return success(ser_division(d))


@app.route("/divisions/<did>/standings", methods=["GET"])
def get_standings(did):
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    d = get_or_404(db.divisions, did)
    seeded = compute_seeded_teams(d)
    limit, offset = parse_pagination()
    total = len(seeded)
    page = seeded[offset:offset + limit]
    return list_response([ser_team(t) for t in page], limit, offset, total)


# ===========================================================================
# TEAMS
# ===========================================================================
@app.route("/divisions/<did>/teams", methods=["POST"])
def register_team(did):
    ctx = get_ctx()
    require_role(ctx, "TeamCaptain")
    d = get_or_404(db.divisions, did)
    body = get_json()
    require_fields(body, "name", "captain_player_id", "expected_division_version")
    captain_id = body["captain_player_id"]
    expected = body["expected_division_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err(E.ERR_INVALID_REQUEST, "expected_division_version must be an integer")
    # Captain ownership: captain_player_id must equal X-User-ID.
    if captain_id != ctx.user_id:
        raise err(E.ERR_FORBIDDEN, "captain_player_id must equal the acting user")
    # Existence of the referenced captain player (left-to-right after division).
    get_or_404(db.players, captain_id)
    # OCC check.
    if expected != d["version"]:
        raise err(E.ERR_STALE_VERSION, "Stale division version")
    # Season-phase gate: team create only while OPEN.
    season = season_of_division(d)
    if not season or season["registration_status"] != "OPEN":
        raise err(E.ERR_SEASON_PHASE, "Team registration only allowed while season is OPEN")
    # Uniqueness: team name unique within division among non-CANCELLED.
    for t in db.teams.values():
        if t["division_id"] == did and t["status"] != "CANCELLED" and t["name"] == body["name"]:
            raise err(E.ERR_DUPLICATE, "Team name already used in this division")
    rec = base_record({
        "division_id": did,
        "captain_player_id": captain_id,
        "name": body["name"],
        "status": "PENDING",
    })
    db.teams[rec["id"]] = rec
    # Captain auto-added as ACTIVE RosterEntry (cascade).
    roster = base_record({
        "team_id": rec["id"],
        "player_id": captain_id,
        "state": "ACTIVE",
    })
    db.roster_entries[roster["id"]] = roster
    # Division version increments.
    touch(d)
    return success(ser_team(rec), status=201)


@app.route("/divisions/<did>/teams", methods=["GET"])
def list_division_teams(did):
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    get_or_404(db.divisions, did)
    status = request.args.get("status")
    recs = [t for t in db.teams.values() if t["division_id"] == did]
    if status:
        recs = [t for t in recs if t["status"] == status]
    return paginate_and_respond(recs, ser_team)


@app.route("/teams/<tid>", methods=["GET"])
def get_team(tid):
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    t = get_or_404(db.teams, tid)
    return success(ser_team(t))


@app.route("/teams", methods=["GET"])
def list_teams():
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    captain_id = request.args.get("captain_player_id")
    status = request.args.get("status")
    recs = list(db.teams.values())
    if captain_id:
        recs = [t for t in recs if t["captain_player_id"] == captain_id]
    if status:
        recs = [t for t in recs if t["status"] == status]
    return paginate_and_respond(recs, ser_team)


def _check_team_ownership(ctx, team):
    """TeamCaptain may act only on a team they captain."""
    if ctx.role == "TeamCaptain":
        if team["captain_player_id"] != ctx.user_id:
            raise err(E.ERR_FORBIDDEN, "Caller does not own this team")


@app.route("/teams/<tid>/pay-fee", methods=["POST"])
def pay_fee(tid):
    ctx = get_ctx()
    require_role(ctx, "TeamCaptain", "LeagueAdmin")
    t = get_or_404(db.teams, tid)
    _check_team_ownership(ctx, t)
    body = get_json()
    require_fields(body, "amount_cents")
    amt = body["amount_cents"]
    if not isinstance(amt, int) or isinstance(amt, bool) or amt < 0:
        raise err(E.ERR_INVALID_REQUEST, "amount_cents must be a non-negative integer")
    pay = _write_payment(tid, "FEE", amt, "REGISTRATION")
    return success(ser_payment(pay), status=201)


def _write_payment(team_id, kind, amount, reason):
    pay = {
        "id": new_id(),
        "team_id": team_id,
        "kind": kind,
        "amount_cents": amount,
        "status": "CAPTURED",
        "reason": reason,
        "created_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.payments[pay["id"]] = pay
    return pay


@app.route("/teams/<tid>/confirm", methods=["POST"])
def confirm_team(tid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    t = get_or_404(db.teams, tid)
    div = division_of_team(t)
    if t["status"] not in ("PENDING", "WAITLISTED"):
        raise err(E.ERR_INVALID_STATE, "Team is not in a confirmable state")
    # For WAITLISTED->CONFIRMED: season must be CLOSED or SCHEDULED.
    if t["status"] == "WAITLISTED":
        season = season_of_team(t)
        if not season or season["registration_status"] not in ("CLOSED", "SCHEDULED"):
            raise err(E.ERR_SEASON_PHASE, "Waitlist promotion only allowed while CLOSED or SCHEDULED")
    # Capacity.
    if compute_confirmed_count(div["id"]) >= div["team_capacity"]:
        raise err(E.ERR_CAPACITY_EXCEEDED, "Division capacity reached")
    # Roster minimum.
    if compute_roster_size(t["id"]) < div["min_roster_size"]:
        raise err(E.ERR_ROSTER_RULE, "Roster below minimum")
    # Fee required when fee-bearing.
    if div["registration_fee_cents"] > 0:
        if compute_fee_charged(t["id"]) < div["registration_fee_cents"]:
            raise err(E.ERR_FEE_REQUIRED, "Captured fee required to confirm")
    t["status"] = "CONFIRMED"
    touch(t)
    touch(div)
    return success(ser_team(t))


@app.route("/teams/<tid>/withdraw", methods=["POST"])
def withdraw_team(tid):
    ctx = get_ctx()
    require_role(ctx, "TeamCaptain", "LeagueAdmin")
    t = get_or_404(db.teams, tid)
    _check_team_ownership(ctx, t)
    div = division_of_team(t)
    season = season_of_team(t)

    if t["status"] in ("PENDING", "WAITLISTED"):
        # Only available while no captured fee exists.
        if compute_fee_charged(t["id"]) > 0:
            raise err(E.ERR_INVALID_STATE, "Team has a captured fee; cannot simple-cancel")
        t["status"] = "CANCELLED"
        _release_team_rosters(t)
        touch(t)
        return success(ser_team(t))

    if t["status"] == "CONFIRMED":
        if not season or season["registration_status"] not in ("CLOSED", "SCHEDULED"):
            raise err(E.ERR_SEASON_PHASE, "Withdraw only allowed while CLOSED or SCHEDULED")
        # No CONFIRMED-score game involving this team.
        for g in db.games.values():
            if t["id"] in (g["home_team_id"], g["away_team_id"]):
                if g["score_status"] == "CONFIRMED":
                    raise err(E.ERR_INVALID_STATE, "Team already has a confirmed-score game")
        # Refund.
        refund_amt, reason = compute_refund(t, force_full=False)
        if refund_amt > 0:
            _write_payment(t["id"], "REFUND", refund_amt, reason)
        elif reason == "NO_REFUND_WITHDRAWAL":
            _write_payment(t["id"], "REFUND", 0, reason)
        t["status"] = "WITHDRAWN_LOCKED"
        touch(t)
        # Cancel SCHEDULED games involving this team; release assignments.
        for g in db.games.values():
            if t["id"] in (g["home_team_id"], g["away_team_id"]):
                if g["schedule_status"] == "SCHEDULED":
                    g["schedule_status"] = "CANCELLED"
                    touch(g)
                    _release_game_assignments(g)
        # confirmed_team_count changes (WITHDRAWN_LOCKED still counts, so no -1
        # until WITHDRAWN; but a slot is freed for waitlist per PRD). Touch div.
        touch(div)
        # Auto-promote highest-seeded WAITLISTED team in division.
        _auto_promote_waitlist(div)
        return success(ser_team(t))

    raise err(E.ERR_INVALID_STATE, "Team is not in a withdrawable state")


def _auto_promote_waitlist(div):
    if compute_confirmed_count(div["id"]) >= div["team_capacity"]:
        return
    waitlisted = [
        t for t in db.teams.values()
        if t["division_id"] == div["id"] and t["status"] == "WAITLISTED"
    ]
    if not waitlisted:
        return
    # Highest-seeded: order by standings seed; created_at ASC tie-break.
    # No games played for waitlisted teams typically; use created_at ASC.
    waitlisted.sort(key=lambda t: (t["created_at"], t["_seq"]))
    promote = waitlisted[0]
    promote["status"] = "CONFIRMED"
    touch(promote)
    touch(div)


def _release_game_assignments(game):
    for a in db.referee_assignments.values():
        if a["game_id"] == game["id"] and a["state"] == "ASSIGNED":
            a["state"] = "RELEASED"
            touch(a)


def compute_refund(team, force_full=False):
    """Return (refund_cents, reason)."""
    captured = compute_fee_charged(team["id"])
    prior = compute_refund_issued(team["id"])
    refundable_base = captured - prior
    if refundable_base < 0:
        refundable_base = 0
    season = season_of_team(team)
    clock = season_clock(season) if season else None
    cutoff = parse_dt(season["refund_full_cutoff_at"]) if season else None

    if force_full or (clock is not None and cutoff is not None and clock <= cutoff):
        refund = refundable_base
        reason = "FULL_WITHDRAWAL"
    elif not _team_has_played_game(team["id"]):
        pct = season["refund_partial_pct"]
        refund = (refundable_base * pct) // 100
        reason = "PARTIAL_WITHDRAWAL"
    else:
        refund = 0
        reason = "NO_REFUND_WITHDRAWAL"
    # Refund integrity bound.
    if refund > refundable_base:
        raise err(E.ERR_REFUND_EXCEEDS_FEE, "Refund exceeds captured fee minus prior refunds")
    return refund, reason


def _team_has_played_game(team_id):
    for g in db.games.values():
        if team_id in (g["home_team_id"], g["away_team_id"]):
            if g["schedule_status"] == "PLAYED" or g["score_status"] == "CONFIRMED":
                return True
    return False


@app.route("/teams/<tid>/refund-adjustment", methods=["POST"])
def refund_adjustment(tid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    t = get_or_404(db.teams, tid)
    body = get_json()
    require_fields(body, "amount_cents")
    amt = body["amount_cents"]
    if not isinstance(amt, int) or isinstance(amt, bool) or amt < 0:
        raise err(E.ERR_INVALID_REQUEST, "amount_cents must be a non-negative integer")
    captured = compute_fee_charged(tid)
    prior = compute_refund_issued(tid)
    if amt > (captured - prior):
        raise err(E.ERR_REFUND_EXCEEDS_FEE, "Refund exceeds captured fee minus prior refunds")
    pay = _write_payment(tid, "REFUND", amt, "ADMIN_ADJUSTMENT")
    return success(ser_payment(pay), status=201)


@app.route("/teams/<tid>/payments", methods=["GET"])
def list_payments(tid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "TeamCaptain")
    t = get_or_404(db.teams, tid)
    _check_team_ownership(ctx, t)
    kind = request.args.get("kind")
    recs = [p for p in db.payments.values() if p["team_id"] == tid]
    if kind:
        recs = [p for p in recs if p["kind"] == kind]
    return paginate_and_respond(recs, ser_payment)


# ===========================================================================
# ROSTER
# ===========================================================================
@app.route("/teams/<tid>/roster", methods=["POST"])
def add_roster(tid):
    ctx = get_ctx()
    require_role(ctx, "TeamCaptain", "LeagueAdmin")
    t = get_or_404(db.teams, tid)
    _check_team_ownership(ctx, t)
    body = get_json()
    require_fields(body, "player_id")
    player = get_or_404(db.players, body["player_id"])
    div = division_of_team(t)
    # Player suspension gate.
    if player["suspension_status"] in ("SUSPENDED", "BANNED"):
        raise err(E.ERR_PLAYER_SUSPENDED, "Player is suspended or banned")
    # Capacity: active count must not exceed max_roster_size.
    if compute_roster_size(tid) >= div["max_roster_size"]:
        raise err(E.ERR_CAPACITY_EXCEEDED, "Roster would exceed max_roster_size")
    # Duplicate active player.
    for r in db.roster_entries.values():
        if r["team_id"] == tid and r["player_id"] == player["id"] and r["state"] == "ACTIVE":
            raise err(E.ERR_ROSTER_RULE, "Player already active on this roster")
    rec = base_record({
        "team_id": tid,
        "player_id": player["id"],
        "state": "ACTIVE",
    })
    db.roster_entries[rec["id"]] = rec
    touch(player)  # is_free_agent recomputed
    touch(t)       # roster_size recomputed
    return success(ser_roster_entry(rec), status=201)


@app.route("/teams/<tid>/roster", methods=["GET"])
def list_roster(tid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "TeamCaptain", "Referee")
    get_or_404(db.teams, tid)
    state = request.args.get("state")
    recs = [r for r in db.roster_entries.values() if r["team_id"] == tid]
    if state:
        recs = [r for r in recs if r["state"] == state]
    return paginate_and_respond(recs, ser_roster_entry)


@app.route("/teams/<tid>/roster/<reid>", methods=["DELETE"])
def release_roster(tid, reid):
    ctx = get_ctx()
    require_role(ctx, "TeamCaptain", "LeagueAdmin")
    t = get_or_404(db.teams, tid)
    _check_team_ownership(ctx, t)
    r = get_or_404(db.roster_entries, reid)
    if r["team_id"] != tid:
        raise err(E.ERR_NOT_FOUND, "Roster entry not found on this team")
    if r["state"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Roster entry is not active")
    r["state"] = "RELEASED"
    touch(r)
    player = db.players.get(r["player_id"])
    if player:
        touch(player)
    touch(t)
    return success(ser_roster_entry(r))


# ===========================================================================
# PLAYERS
# ===========================================================================
@app.route("/players", methods=["POST"])
def create_player():
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "TeamCaptain")
    body = get_json()
    require_fields(body, "full_name", "email")
    # Email globally unique among non-CANCELLED players (players have no
    # CANCELLED status — uniqueness is simply global among existing players).
    for p in db.players.values():
        if p["email"] == body["email"]:
            raise err(E.ERR_DUPLICATE, "Email already in use")
    rec = base_record({
        "full_name": body["full_name"],
        "email": body["email"],
        "conduct_points": 0,
        "suspension_status": "CLEAR",
        "suspended_until_game_index": 0,
    })
    db.players[rec["id"]] = rec
    return success(ser_player(rec), status=201)


@app.route("/players/<pid>", methods=["GET"])
def get_player(pid):
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    p = get_or_404(db.players, pid)
    return success(ser_player(p))


@app.route("/players/<pid>/roster-entries", methods=["GET"])
def list_player_roster_entries(pid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "TeamCaptain", "Referee")
    get_or_404(db.players, pid)
    state = request.args.get("state")
    recs = [r for r in db.roster_entries.values() if r["player_id"] == pid]
    if state:
        recs = [r for r in recs if r["state"] == state]
    return paginate_and_respond(recs, ser_roster_entry)


# ===========================================================================
# VENUES
# ===========================================================================
@app.route("/venues", methods=["POST"])
def create_venue():
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    body = get_json()
    require_fields(body, "name", "field_count")
    fc = body["field_count"]
    if not isinstance(fc, int) or isinstance(fc, bool) or fc < 1:
        raise err(E.ERR_INVALID_REQUEST, "field_count must be >= 1")
    buf = body.get("turnover_buffer_minutes", 30)
    if buf is None:
        buf = 30
    if not isinstance(buf, int) or isinstance(buf, bool) or buf < 0:
        raise err(E.ERR_INVALID_REQUEST, "turnover_buffer_minutes must be a non-negative integer")
    rec = base_record({
        "name": body["name"],
        "field_count": fc,
        "turnover_buffer_minutes": buf,
    })
    db.venues[rec["id"]] = rec
    return success(ser_venue(rec), status=201)


@app.route("/venues/<vid>", methods=["GET"])
def get_venue(vid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "TeamCaptain", "Referee")
    v = get_or_404(db.venues, vid)
    return success(ser_venue(v))


# ===========================================================================
# REFEREES
# ===========================================================================
@app.route("/referees", methods=["POST"])
def create_referee():
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    body = get_json()
    require_fields(body, "full_name", "certified_sports")
    cs = body["certified_sports"]
    if not isinstance(cs, list):
        raise err(E.ERR_INVALID_REQUEST, "certified_sports must be an array")
    for sport in cs:
        if sport not in SPORTS:
            raise err(E.ERR_INVALID_REQUEST, "Invalid sport in certified_sports")
    rec = base_record({
        "full_name": body["full_name"],
        "certified_sports": cs,
    })
    db.referees[rec["id"]] = rec
    return success(ser_referee(rec), status=201)


@app.route("/referees/<rid>", methods=["GET"])
def get_referee(rid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "Referee")
    r = get_or_404(db.referees, rid)
    return success(ser_referee(r))


@app.route("/referees/<rid>/assignments", methods=["GET"])
def list_referee_assignments(rid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "Referee")
    get_or_404(db.referees, rid)
    state = request.args.get("state")
    recs = [a for a in db.referee_assignments.values() if a["referee_id"] == rid]
    if state:
        recs = [a for a in recs if a["state"] == state]
    return paginate_and_respond(recs, ser_assignment)


# ===========================================================================
# GAMES
# ===========================================================================
@app.route("/divisions/<did>/games", methods=["POST"])
def schedule_game(did):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    d = get_or_404(db.divisions, did)
    body = get_json()
    require_fields(body, "home_team_id", "away_team_id", "venue_id",
                   "field_index", "round_index", "starts_at", "ends_at")
    stage = body.get("stage", "REGULAR")
    if stage is None:
        stage = "REGULAR"
    if stage not in GAME_STAGES:
        raise err(E.ERR_INVALID_REQUEST, "Invalid stage")
    # Existence: teams + venue (after division).
    home = get_or_404(db.teams, body["home_team_id"])
    away = get_or_404(db.teams, body["away_team_id"])
    venue = get_or_404(db.venues, body["venue_id"])
    # Body well-formedness.
    ri = body["round_index"]
    if not isinstance(ri, int) or isinstance(ri, bool) or ri < 1:
        raise err(E.ERR_INVALID_REQUEST, "round_index must be >= 1")
    fi = body["field_index"]
    if not isinstance(fi, int) or isinstance(fi, bool):
        raise err(E.ERR_INVALID_REQUEST, "field_index must be an integer")
    if fi < 1 or fi > venue["field_count"]:
        raise err(E.ERR_INVALID_REQUEST, "field_index out of range")
    starts = parse_dt(body["starts_at"])
    ends = parse_dt(body["ends_at"])
    if starts is None or ends is None:
        raise err(E.ERR_INVALID_REQUEST, "Invalid datetime")
    if not (ends > starts):
        raise err(E.ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    # Matchup integrity.
    if home["id"] == away["id"]:
        raise err(E.ERR_INVALID_MATCHUP, "Home and away teams must differ")
    if home["status"] != "CONFIRMED" or away["status"] != "CONFIRMED":
        raise err(E.ERR_INVALID_MATCHUP, "Both teams must be CONFIRMED")
    if home["division_id"] != did or away["division_id"] != did:
        raise err(E.ERR_INVALID_MATCHUP, "Both teams must be in the game's division")
    # Venue overlap.
    if _venue_conflict(body["venue_id"], fi, starts, ends, venue, exclude_game_id=None):
        raise err(E.ERR_VENUE_DOUBLE_BOOKED, "Venue/field double-booked")
    rec = base_record({
        "division_id": did,
        "home_team_id": home["id"],
        "away_team_id": away["id"],
        "venue_id": venue["id"],
        "field_index": fi,
        "round_index": ri,
        "stage": stage,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "schedule_status": "SCHEDULED",
        "score_status": "PENDING",
        "home_score": None,
        "away_score": None,
        "forfeiting_team_id": None,
    })
    db.games[rec["id"]] = rec
    return success(ser_game(rec), status=201)


def _venue_conflict(venue_id, field_index, starts, ends, venue, exclude_game_id):
    buf_min = venue["turnover_buffer_minutes"]
    from datetime import timedelta
    buf = timedelta(minutes=buf_min)
    for g in db.games.values():
        if g["id"] == exclude_game_id:
            continue
        if g["venue_id"] != venue_id or g["field_index"] != field_index:
            continue
        if g["schedule_status"] not in ("SCHEDULED", "RESCHEDULE_REQUESTED"):
            continue
        g_start = parse_dt(g["starts_at"])
        g_end = parse_dt(g["ends_at"])
        if g_start is None or g_end is None:
            continue
        # new at [starts, ends), existing at [g_start, g_end). Buffer at the end
        # of each: conflict iff starts < (g_end + buf) AND g_start < (ends + buf).
        if starts < (g_end + buf) and g_start < (ends + buf):
            return True
    return False


@app.route("/divisions/<did>/games", methods=["GET"])
def list_division_games(did):
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    get_or_404(db.divisions, did)
    recs = [g for g in db.games.values() if g["division_id"] == did]
    for field in ("schedule_status", "score_status", "stage"):
        val = request.args.get(field)
        if val:
            recs = [g for g in recs if g[field] == val]
    ri = request.args.get("round_index")
    if ri is not None:
        try:
            ri_int = int(ri)
        except (ValueError, TypeError):
            raise err(E.ERR_INVALID_REQUEST, "round_index must be an integer")
        recs = [g for g in recs if g["round_index"] == ri_int]
    return paginate_and_respond(recs, ser_game)


@app.route("/games/<gid>", methods=["GET"])
def get_game(gid):
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    g = get_or_404(db.games, gid)
    return success(ser_game(g))


@app.route("/games", methods=["GET"])
def list_games():
    ctx = get_ctx()
    require_role(ctx, *ROLES)
    recs = list(db.games.values())
    home = request.args.get("home_team_id")
    away = request.args.get("away_team_id")
    venue = request.args.get("venue_id")
    forfeiting = request.args.get("forfeiting_team_id")
    schedule_status = request.args.get("schedule_status")
    if home:
        recs = [g for g in recs if g["home_team_id"] == home]
    if away:
        recs = [g for g in recs if g["away_team_id"] == away]
    if venue:
        recs = [g for g in recs if g["venue_id"] == venue]
    if forfeiting:
        recs = [g for g in recs if g["forfeiting_team_id"] == forfeiting]
    if schedule_status:
        recs = [g for g in recs if g["schedule_status"] == schedule_status]
    return paginate_and_respond(recs, ser_game)


def _captain_owns_game(ctx, game):
    if ctx.role != "TeamCaptain":
        return True
    home = db.teams.get(game["home_team_id"])
    away = db.teams.get(game["away_team_id"])
    owned = (home and home["captain_player_id"] == ctx.user_id) or \
            (away and away["captain_player_id"] == ctx.user_id)
    return bool(owned)


@app.route("/games/<gid>/request-reschedule", methods=["POST"])
def request_reschedule(gid):
    ctx = get_ctx()
    require_role(ctx, "TeamCaptain")
    g = get_or_404(db.games, gid)
    if not _captain_owns_game(ctx, g):
        raise err(E.ERR_FORBIDDEN, "Caller does not own this game")
    season = season_of_game(g)
    if not season or season["registration_status"] not in ("SCHEDULED", "IN_PLAY"):
        raise err(E.ERR_SEASON_PHASE, "Reschedule only allowed while SCHEDULED or IN_PLAY")
    if g["schedule_status"] != "SCHEDULED":
        raise err(E.ERR_INVALID_STATE, "Game is not in SCHEDULED state")
    if g["score_status"] != "PENDING":
        raise err(E.ERR_INVALID_STATE, "Score must be PENDING to request reschedule")
    g["schedule_status"] = "RESCHEDULE_REQUESTED"
    touch(g)
    return success(ser_game(g))


@app.route("/games/<gid>/reschedule", methods=["POST"])
def reschedule(gid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    g = get_or_404(db.games, gid)
    body = get_json()
    require_fields(body, "venue_id", "field_index", "starts_at", "ends_at")
    venue = get_or_404(db.venues, body["venue_id"])
    fi = body["field_index"]
    if not isinstance(fi, int) or isinstance(fi, bool):
        raise err(E.ERR_INVALID_REQUEST, "field_index must be an integer")
    if fi < 1 or fi > venue["field_count"]:
        raise err(E.ERR_INVALID_REQUEST, "field_index out of range")
    starts = parse_dt(body["starts_at"])
    ends = parse_dt(body["ends_at"])
    if starts is None or ends is None:
        raise err(E.ERR_INVALID_REQUEST, "Invalid datetime")
    if not (ends > starts):
        raise err(E.ERR_INVALID_REQUEST, "ends_at must be after starts_at")
    season = season_of_game(g)
    if not season or season["registration_status"] not in ("SCHEDULED", "IN_PLAY"):
        raise err(E.ERR_SEASON_PHASE, "Reschedule only allowed while SCHEDULED or IN_PLAY")
    if g["schedule_status"] != "RESCHEDULE_REQUESTED":
        raise err(E.ERR_INVALID_STATE, "Game is not in RESCHEDULE_REQUESTED state")
    # New starts_at must be in the future relative to clock_now.
    clock = season_clock(season)
    if clock is not None and not (starts > clock):
        raise err(E.ERR_INVALID_REQUEST, "New starts_at must be in the future")
    # Referee overlap for retained assignments.
    if _referee_conflict_for_game(g, starts, ends, exclude_game_id=g["id"]):
        raise err(E.ERR_REFEREE_DOUBLE_BOOKED, "Referee double-booked at new slot")
    # Venue overlap.
    if _venue_conflict(body["venue_id"], fi, starts, ends, venue, exclude_game_id=g["id"]):
        raise err(E.ERR_VENUE_DOUBLE_BOOKED, "Venue/field double-booked at new slot")
    g["venue_id"] = venue["id"]
    g["field_index"] = fi
    g["starts_at"] = body["starts_at"]
    g["ends_at"] = body["ends_at"]
    g["schedule_status"] = "SCHEDULED"
    touch(g)
    return success(ser_game(g))


def _referee_conflict_for_game(game, starts, ends, exclude_game_id):
    """Half-open interval overlap for every retained ASSIGNED assignment."""
    ref_ids = [
        a["referee_id"] for a in db.referee_assignments.values()
        if a["game_id"] == game["id"] and a["state"] == "ASSIGNED"
    ]
    for ref_id in ref_ids:
        if _referee_overlaps(ref_id, starts, ends, exclude_game_id):
            return True
    return False


def _referee_overlaps(referee_id, starts, ends, exclude_game_id):
    for a in db.referee_assignments.values():
        if a["referee_id"] != referee_id or a["state"] != "ASSIGNED":
            continue
        og = db.games.get(a["game_id"])
        if og is None or og["id"] == exclude_game_id:
            continue
        og_start = parse_dt(og["starts_at"])
        og_end = parse_dt(og["ends_at"])
        if og_start is None or og_end is None:
            continue
        # Half-open [a1,e1) and [a2,e2): conflict iff a1 < e2 AND a2 < e1.
        if starts < og_end and og_start < ends:
            return True
    return False


@app.route("/games/<gid>/forfeit", methods=["POST"])
def forfeit_game(gid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "TeamCaptain")
    g = get_or_404(db.games, gid)
    if not _captain_owns_game(ctx, g):
        raise err(E.ERR_FORBIDDEN, "Caller does not own this game")
    body = get_json()
    require_fields(body, "forfeiting_team_id")
    ft = body["forfeiting_team_id"]
    if g["schedule_status"] != "SCHEDULED":
        raise err(E.ERR_INVALID_STATE, "Game is not in SCHEDULED state")
    if g["score_status"] not in ("PENDING", "SUBMITTED"):
        raise err(E.ERR_INVALID_STATE, "Score must be PENDING or SUBMITTED to forfeit")
    if ft not in (g["home_team_id"], g["away_team_id"]):
        raise err(E.ERR_INVALID_MATCHUP, "forfeiting_team_id must be one of the two teams")
    g["schedule_status"] = "FORFEITED"
    g["score_status"] = "CONFIRMED"
    g["forfeiting_team_id"] = ft
    touch(g)
    # Recompute standings for both teams (touch them).
    _touch_team(g["home_team_id"])
    _touch_team(g["away_team_id"])
    # Release referee assignments.
    _release_game_assignments(g)
    return success(ser_game(g))


def _touch_team(team_id):
    t = db.teams.get(team_id)
    if t:
        touch(t)


@app.route("/games/<gid>/submit-score", methods=["POST"])
def submit_score(gid):
    ctx = get_ctx()
    require_role(ctx, "TeamCaptain", "Referee")
    g = get_or_404(db.games, gid)
    # Ownership for captains.
    if ctx.role == "TeamCaptain" and not _captain_owns_game(ctx, g):
        raise err(E.ERR_FORBIDDEN, "Caller does not own this game")
    body = get_json()
    require_fields(body, "home_score", "away_score", "expected_game_version")
    hs = body["home_score"]
    as_ = body["away_score"]
    ev = body["expected_game_version"]
    if not isinstance(ev, int) or isinstance(ev, bool):
        raise err(E.ERR_INVALID_REQUEST, "expected_game_version must be an integer")
    for v in (hs, as_):
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise err(E.ERR_INVALID_REQUEST, "Scores must be non-negative integers")
    # OCC check (priority 5, before season phase).
    if ev != g["version"]:
        raise err(E.ERR_STALE_VERSION, "Stale game version")
    # Season-phase gate.
    season = season_of_game(g)
    if not season or season["registration_status"] not in ("SCHEDULED", "IN_PLAY"):
        raise err(E.ERR_SEASON_PHASE, "Score submission only allowed while SCHEDULED or IN_PLAY")
    # State: schedule_status SCHEDULED and score_status PENDING or DISPUTED.
    if g["schedule_status"] != "SCHEDULED":
        raise err(E.ERR_INVALID_STATE, "Game schedule status does not allow scoring")
    if g["score_status"] not in ("PENDING", "DISPUTED"):
        raise err(E.ERR_INVALID_STATE, "Score status does not allow submission")
    # If resubmitting from DISPUTED, only the HEAD referee may act.
    if g["score_status"] == "DISPUTED":
        if ctx.role != "Referee" or not _is_head_referee(ctx, g):
            raise err(E.ERR_FORBIDDEN, "Only the HEAD referee may resubmit a disputed score")
    # Clock must have reached starts_at.
    clock = season_clock(season)
    starts = parse_dt(g["starts_at"])
    if clock is not None and starts is not None and clock < starts:
        raise err(E.ERR_INVALID_STATE, "Game has not started yet")
    g["home_score"] = hs
    g["away_score"] = as_
    g["score_status"] = "SUBMITTED"
    touch(g)
    return success(ser_game(g))


def _is_head_referee(ctx, game):
    for a in db.referee_assignments.values():
        if (a["game_id"] == game["id"] and a["role"] == "HEAD"
                and a["state"] == "ASSIGNED" and a["referee_id"] == ctx.user_id):
            return True
    return False


@app.route("/games/<gid>/confirm-score", methods=["POST"])
def confirm_score(gid):
    ctx = get_ctx()
    require_role(ctx, "Referee")
    g = get_or_404(db.games, gid)
    if g["score_status"] != "SUBMITTED":
        raise err(E.ERR_INVALID_STATE, "Score is not in SUBMITTED state")
    # A HEAD assignment in ASSIGNED state must exist and be acted by its referee.
    head = None
    for a in db.referee_assignments.values():
        if a["game_id"] == g["id"] and a["role"] == "HEAD" and a["state"] == "ASSIGNED":
            head = a
            break
    if head is None:
        raise err(E.ERR_INVALID_STATE, "No assigned HEAD referee for this game")
    if head["referee_id"] != ctx.user_id:
        raise err(E.ERR_FORBIDDEN, "Only the assigned HEAD referee may confirm")
    g["score_status"] = "CONFIRMED"
    g["schedule_status"] = "PLAYED"
    touch(g)
    _release_game_assignments(g)
    _touch_team(g["home_team_id"])
    _touch_team(g["away_team_id"])
    return success(ser_game(g))


@app.route("/games/<gid>/dispute-score", methods=["POST"])
def dispute_score(gid):
    ctx = get_ctx()
    require_role(ctx, "TeamCaptain")
    g = get_or_404(db.games, gid)
    if not _captain_owns_game(ctx, g):
        raise err(E.ERR_FORBIDDEN, "Caller does not own this game")
    if g["score_status"] != "SUBMITTED":
        raise err(E.ERR_INVALID_STATE, "Score is not in SUBMITTED state")
    # Losing captain only: the captain of whichever team trails.
    hs = g["home_score"]
    as_ = g["away_score"]
    home = db.teams.get(g["home_team_id"])
    away = db.teams.get(g["away_team_id"])
    losing_team_id = None
    if hs is not None and as_ is not None:
        if hs < as_:
            losing_team_id = g["home_team_id"]
        elif as_ < hs:
            losing_team_id = g["away_team_id"]
    if losing_team_id is None:
        raise err(E.ERR_FORBIDDEN, "Only the losing captain may dispute")
    losing = db.teams.get(losing_team_id)
    if not losing or losing["captain_player_id"] != ctx.user_id:
        raise err(E.ERR_FORBIDDEN, "Only the losing captain may dispute")
    g["score_status"] = "DISPUTED"
    touch(g)
    return success(ser_game(g))


# ===========================================================================
# REFEREE ASSIGNMENTS
# ===========================================================================
@app.route("/games/<gid>/referee-assignments", methods=["POST"])
def assign_referee(gid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    g = get_or_404(db.games, gid)
    body = get_json()
    require_fields(body, "referee_id")
    ref = get_or_404(db.referees, body["referee_id"])
    role = body.get("role", "HEAD")
    if role is None:
        role = "HEAD"
    if role not in ASSIGN_ROLES:
        raise err(E.ERR_INVALID_REQUEST, "Invalid role")
    # Referee overlap.
    starts = parse_dt(g["starts_at"])
    ends = parse_dt(g["ends_at"])
    if starts is not None and ends is not None:
        if _referee_overlaps(ref["id"], starts, ends, exclude_game_id=g["id"]):
            raise err(E.ERR_REFEREE_DOUBLE_BOOKED, "Referee double-booked")
    rec = base_record({
        "game_id": g["id"],
        "referee_id": ref["id"],
        "role": role,
        "state": "ASSIGNED",
    })
    db.referee_assignments[rec["id"]] = rec
    return success(ser_assignment(rec), status=201)


@app.route("/games/<gid>/referee-assignments", methods=["GET"])
def list_game_assignments(gid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "Referee")
    get_or_404(db.games, gid)
    state = request.args.get("state")
    recs = [a for a in db.referee_assignments.values() if a["game_id"] == gid]
    if state:
        recs = [a for a in recs if a["state"] == state]
    return paginate_and_respond(recs, ser_assignment)


@app.route("/games/<gid>/referee-assignments/<aid>", methods=["DELETE"])
def release_assignment(gid, aid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    get_or_404(db.games, gid)
    a = get_or_404(db.referee_assignments, aid)
    if a["game_id"] != gid:
        raise err(E.ERR_NOT_FOUND, "Assignment not found on this game")
    if a["state"] != "ASSIGNED":
        raise err(E.ERR_INVALID_STATE, "Assignment is not in ASSIGNED state")
    a["state"] = "RELEASED"
    touch(a)
    return success(ser_assignment(a))


# ===========================================================================
# CONDUCT REPORTS
# ===========================================================================
@app.route("/conduct-reports", methods=["POST"])
def file_conduct_report():
    ctx = get_ctx()
    require_role(ctx, "Referee", "LeagueAdmin", "ConductOfficer")
    body = get_json()
    require_fields(body, "game_id", "player_id", "severity")
    game = get_or_404(db.games, body["game_id"])
    player = get_or_404(db.players, body["player_id"])
    if body["severity"] not in SEVERITIES:
        raise err(E.ERR_INVALID_REQUEST, "Invalid severity")
    rec = base_record({
        "game_id": game["id"],
        "player_id": player["id"],
        "severity": body["severity"],
        "status": "FILED",
        "points": 0,
    })
    db.conduct_reports[rec["id"]] = rec
    return success(ser_report(rec), status=201)


@app.route("/conduct-reports/<rid>", methods=["GET"])
def get_conduct_report(rid):
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "ConductOfficer", "TeamCaptain", "Referee")
    r = get_or_404(db.conduct_reports, rid)
    return success(ser_report(r))


@app.route("/conduct-reports", methods=["GET"])
def list_conduct_reports():
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin", "ConductOfficer", "Referee")
    recs = list(db.conduct_reports.values())
    pid = request.args.get("player_id")
    gid = request.args.get("game_id")
    status = request.args.get("status")
    if pid:
        recs = [r for r in recs if r["player_id"] == pid]
    if gid:
        recs = [r for r in recs if r["game_id"] == gid]
    if status:
        recs = [r for r in recs if r["status"] == status]
    return paginate_and_respond(recs, ser_report)


@app.route("/conduct-reports/<rid>/transition", methods=["POST"])
def transition_conduct_report(rid):
    ctx = get_ctx()
    require_role(ctx, "ConductOfficer", "TeamCaptain")
    r = get_or_404(db.conduct_reports, rid)
    body = get_json()
    require_fields(body, "target")
    target = body["target"]
    valid_targets = {"UNDER_REVIEW", "UPHELD", "DISMISSED", "APPEALED"}
    if target not in valid_targets:
        raise err(E.ERR_INVALID_REQUEST, "Invalid target")
    cur = r["status"]
    player = db.players.get(r["player_id"])

    if target == "UNDER_REVIEW":
        require_role(ctx, "ConductOfficer")
        if cur != "FILED":
            raise err(E.ERR_INVALID_STATE, "Report not in FILED state")
        r["status"] = "UNDER_REVIEW"
        touch(r)
    elif target == "UPHELD":
        require_role(ctx, "ConductOfficer")
        if cur not in ("UNDER_REVIEW", "APPEALED"):
            raise err(E.ERR_INVALID_STATE, "Report cannot be upheld from current state")
        from_under_review = (cur == "UNDER_REVIEW")
        r["status"] = "UPHELD"
        r["points"] = SEVERITY_POINTS[r["severity"]]
        touch(r)
        if player:
            game = db.games.get(r["game_id"])
            trig = game["round_index"] if (from_under_review and game) else None
            recompute_player_suspension(player, triggering_round_index=trig)
            touch(player)
    elif target == "DISMISSED":
        require_role(ctx, "ConductOfficer")
        if cur not in ("UNDER_REVIEW", "APPEALED"):
            raise err(E.ERR_INVALID_STATE, "Report cannot be dismissed from current state")
        was_counting = (cur == "APPEALED")
        r["status"] = "DISMISSED"
        r["points"] = 0
        touch(r)
        if player and was_counting:
            recompute_player_suspension(player, triggering_round_index=None)
            touch(player)
    elif target == "APPEALED":
        require_role(ctx, "TeamCaptain")
        if cur != "UPHELD":
            raise err(E.ERR_INVALID_STATE, "Only an upheld report may be appealed")
        # Captain must roster the cited player on a team they captain (ACTIVE).
        if not _captain_rosters_player(ctx, r["player_id"]):
            raise err(E.ERR_FORBIDDEN, "Caller does not roster the cited player")
        r["status"] = "APPEALED"
        touch(r)
        # points and conduct_points unchanged.

    return success(ser_report(r))


def _captain_rosters_player(ctx, player_id):
    for re in db.roster_entries.values():
        if re["player_id"] != player_id or re["state"] != "ACTIVE":
            continue
        team = db.teams.get(re["team_id"])
        if team and team["captain_player_id"] == ctx.user_id:
            return True
    return False


# ===========================================================================
# CLOCK (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ctx = get_ctx()
    require_role(ctx, "LeagueAdmin")
    body = get_json()
    require_fields(body, "to_iso8601")
    dt = parse_dt(body["to_iso8601"])
    if dt is None:
        raise err(E.ERR_INVALID_REQUEST, "Invalid to_iso8601")
    for s in db.seasons.values():
        s["clock_now"] = body["to_iso8601"]  # no version bump
    return success({})


# ---------------------------------------------------------------------------
# Health (harness readiness probe)
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return success({})


if __name__ == "__main__":
    # werkzeug's server_bind() calls socket.getfqdn(host) for the WSGI SERVER_NAME.
    # On macOS, getfqdn("0.0.0.0") triggers a reverse-DNS lookup that can block ~5s,
    # which under the per-test-server restart harness (server rebooted before every
    # test, 8 rounds concurrent) blows the boot timeout. SERVER_NAME is unused by this
    # API, so short-circuit the lookup to keep boot well under a second.
    import socket as _socket
    _socket.getfqdn = lambda *args, **kwargs: "localhost"
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
