"""Matches: scheduling, server configuration, results, forfeits, disputes, broadcast."""

import datetime as _dt

from flask import Blueprint

import domain
from errors import fail
from guards import coach_participates
from http_util import (
    created,
    endpoint,
    listing,
    ok,
    opt_dt,
    opt_int,
    opt_str,
    present,
    req_dt,
    req_enum,
    req_int,
    req_str,
)
from serialize import dump
from store import db, find, must_find, new_record, touch

bp = Blueprint("routes_d", __name__)

MATCH_READ_ROLES = (
    "LeagueAdmin",
    "DistrictAdmin",
    "AthleticDirector",
    "Coach",
    "EligibilityOfficer",
    "IntegrityOfficer",
)
DISPUTE_REASONS = ("SCORE_MISMATCH", "SERVER_FAULT", "INELIGIBLE_PLAYER", "CONDUCT")
MATCH_FILTERS = (
    "season_id",
    "home_team_id",
    "away_team_id",
    "broadcast_school_id",
    "dispute_filed_by_team_id",
    "winner_team_id",
    "forfeiting_team_id",
    "play_status",
    "result_status",
    "dispute_status",
    "broadcast_status",
)


def _participants(match):
    return (match["home_team_id"], match["away_team_id"])


def _winner_from(match, home_games, away_games):
    if home_games > away_games:
        return match["home_team_id"]
    if away_games > home_games:
        return match["away_team_id"]
    return None


# ---------------------------------------------------------------------------
# scheduling
# ---------------------------------------------------------------------------
@bp.post("/matches")
@endpoint("LeagueAdmin")
def schedule_match(ctx):
    body = ctx.body
    season_id = req_str(body, "season_id")
    home_team_id = req_str(body, "home_team_id")
    away_team_id = req_str(body, "away_team_id")
    start_at = req_dt(body, "scheduled_start_at")
    if home_team_id == away_team_id:
        fail("ERR_SELF_MATCH_FORBIDDEN", "A match needs two distinct participants.")
    season = find("season", season_id)
    if season is None:
        fail("ERR_SEASON_NOT_FOUND", "No season with that identifier exists.")
    home = find("team", home_team_id)
    away = find("team", away_team_id)
    if home is None or away is None:
        fail("ERR_TEAM_NOT_FOUND", "No team with that identifier exists.")
    if home["season_id"] != season_id or away["season_id"] != season_id:
        fail("ERR_TEAM_SEASON_MISMATCH", "Both participants must belong to the match's season.")
    title = find("title", season["title_id"])
    duration = title["match_duration_minutes"] if title else 60
    end_at = start_at + _dt.timedelta(minutes=duration)
    if start_at < season["roster_lock_at"] or end_at > season["regular_season_end_at"]:
        fail("ERR_MATCH_OUTSIDE_SEASON_WINDOW", "The match falls outside the season's calendar.")
    pool_id = title["server_pool_id"] if title else None
    capacity = title["server_pool_capacity"] if title else 1
    if domain.server_pool_conflict(pool_id, start_at, end_at, capacity):
        fail("ERR_SERVER_POOL_CAPACITY_EXCEEDED", "The server pool is at capacity for that window.")
    match = new_record(
        "match",
        season_id=season_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        scheduled_start_at=start_at,
        scheduled_end_at=end_at,
        server_pool_id=pool_id,
        region_code=None,
        patch_version=None,
        play_status="SCHEDULED",
        result_status="AWAITING_REPORTS",
        dispute_status="NONE",
        broadcast_status="NONE",
        broadcast_school_id=None,
        broadcast_start_at=None,
        broadcast_end_at=None,
        spectator_strikes=0,
        home_reported_home_games_won=None,
        home_reported_away_games_won=None,
        away_reported_home_games_won=None,
        away_reported_away_games_won=None,
        home_games_won=None,
        away_games_won=None,
        result_confirmed_at=None,
        dispute_deadline_at=None,
        dispute_filed_by_team_id=None,
        dispute_reason_code=None,
        winner_team_id=None,
        forfeiting_team_id=None,
        home_points_awarded=0,
        away_points_awarded=0,
    )
    return created(dump(match))


@bp.get("/matches/<match_id>")
@endpoint(*MATCH_READ_ROLES)
def read_match(ctx, match_id):
    return ok(dump(must_find("match", match_id)))


@bp.get("/matches")
@endpoint(*MATCH_READ_ROLES)
def list_matches(ctx):
    return listing("match", MATCH_FILTERS, dump)


@bp.post("/matches/<match_id>/server-config")
@endpoint("LeagueAdmin")
def configure_match_server(ctx, match_id):
    match = must_find("match", match_id)
    region_code = req_str(ctx.body, "region_code", 1, 40)
    patch_version = req_str(ctx.body, "patch_version", 1, 40)
    season = domain.season_of(match)
    if season is None or season["status"] not in (
        "ROSTER_LOCKED",
        "REGULAR_SEASON",
        "PLAYOFFS",
    ):
        fail("ERR_INVALID_SEASON_STAGE", "The season stage does not permit server configuration.")
    if match["play_status"] != "SCHEDULED":
        fail("ERR_INVALID_MATCH_STATE", "Only a scheduled match may be configured.")
    domain.update(
        match,
        region_code=region_code,
        patch_version=patch_version,
        play_status="SERVER_READY",
    )
    touch(match)
    return ok(dump(match))


# ---------------------------------------------------------------------------
# result reporting
# ---------------------------------------------------------------------------
@bp.post("/matches/<match_id>/result-reports")
@endpoint("Coach")
def report_result(ctx, match_id):
    existing = find("match", match_id)
    if existing is not None:
        coach_participates(ctx, existing)
    match = must_find("match", match_id)
    body = ctx.body
    reporting_team_id = req_str(body, "reporting_team_id")
    home_games_won = req_int(body, "home_games_won", low=0)
    away_games_won = req_int(body, "away_games_won", low=0)
    expected = req_int(body, "expected_match_version")
    if expected != match["version"]:
        fail("ERR_STALE_VERSION", "The supplied expected_match_version is not current.")
    season = domain.season_of(match)
    if season is None or season["status"] not in ("REGULAR_SEASON", "PLAYOFFS"):
        fail("ERR_INVALID_SEASON_STAGE", "Results are reported only during play.")
    if match["play_status"] != "SERVER_READY":
        fail("ERR_INVALID_MATCH_STATE", "The match is not ready for result reports.")
    if reporting_team_id not in _participants(match):
        fail("ERR_TEAM_NOT_MATCH_PARTICIPANT", "The reporting team does not play in this match.")
    reporting_team = find("team", reporting_team_id)
    if reporting_team is None or reporting_team["coach_id"] != ctx.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the reporting team's own coach may report.")
    if reporting_team_id == match["home_team_id"]:
        match["home_reported_home_games_won"] = home_games_won
        match["home_reported_away_games_won"] = away_games_won
    else:
        match["away_reported_home_games_won"] = home_games_won
        match["away_reported_away_games_won"] = away_games_won
    home_done = match["home_reported_home_games_won"] is not None
    away_done = match["away_reported_home_games_won"] is not None
    if not (home_done and away_done):
        match["result_status"] = "PARTIALLY_REPORTED"
        touch(match)
        return ok(dump(match))
    agreed = (
        match["away_reported_home_games_won"] == match["home_reported_home_games_won"]
        and match["away_reported_away_games_won"] == match["home_reported_away_games_won"]
    )
    match["play_status"] = "PLAYED"
    if not agreed:
        match["result_status"] = "CONTESTED"
        touch(match)
        return ok(dump(match))
    match["result_status"] = "CONFIRMED"
    match["home_games_won"] = match["home_reported_home_games_won"]
    match["away_games_won"] = match["home_reported_away_games_won"]
    match["winner_team_id"] = _winner_from(
        match, match["home_games_won"], match["away_games_won"]
    )
    match["result_confirmed_at"] = db.now
    match["dispute_deadline_at"] = domain.compute_dispute_deadline(match)
    touch(match)
    domain.award_points(match)
    domain.mark_seeding_stale(
        season, [find("team", match["home_team_id"]), find("team", match["away_team_id"])]
    )
    return ok(dump(match))


@bp.post("/matches/<match_id>/finalize")
@endpoint("LeagueAdmin")
def finalize_match(ctx, match_id):
    match = must_find("match", match_id)
    body = ctx.body
    override_home = opt_int(body, "override_home_games_won", None, low=0)
    override_away = opt_int(body, "override_away_games_won", None, low=0)
    result_status = match["result_status"]
    if result_status == "CONTESTED":
        if override_home is None or override_away is None:
            fail(
                "ERR_INVALID_REQUEST",
                "Finalizing a contested result requires both override game counts.",
            )
    elif result_status in ("CONFIRMED", "ADJUDICATED"):
        if present(body, "override_home_games_won") or present(body, "override_away_games_won"):
            fail(
                "ERR_INVALID_REQUEST",
                "Finalizing a decided result forbids the override game counts.",
            )
    if match["play_status"] != "PLAYED" or result_status not in (
        "CONFIRMED",
        "ADJUDICATED",
        "CONTESTED",
    ):
        fail("ERR_INVALID_MATCH_STATE", "The match cannot be finalized from its current state.")
    if result_status == "CONTESTED":
        match["home_games_won"] = override_home
        match["away_games_won"] = override_away
        match["winner_team_id"] = _winner_from(match, override_home, override_away)
        match["result_status"] = "ADJUDICATED"
        match["result_confirmed_at"] = db.now
        match["dispute_deadline_at"] = domain.compute_dispute_deadline(match)
        match["play_status"] = "FINALIZED"
        touch(match)
        domain.award_points(match)
        domain.mark_seeding_stale(
            domain.season_of(match),
            [find("team", match["home_team_id"]), find("team", match["away_team_id"])],
        )
    else:
        match["play_status"] = "FINALIZED"
        touch(match)
    return ok(dump(match))


@bp.post("/matches/<match_id>/forfeit")
@endpoint("LeagueAdmin")
def forfeit_match(ctx, match_id):
    match = must_find("match", match_id)
    forfeiting_team_id = req_str(ctx.body, "forfeiting_team_id")
    opt_str(ctx.body, "reason_note", None, 1, 500)
    if match["play_status"] not in ("SCHEDULED", "SERVER_READY"):
        fail("ERR_INVALID_MATCH_STATE", "Only an unplayed match may be forfeited.")
    if forfeiting_team_id not in _participants(match):
        fail("ERR_TEAM_NOT_MATCH_PARTICIPANT", "The named team does not play in this match.")
    domain.apply_forfeit(match, forfeiting_team_id, {"type": "DIRECT"})
    return ok(dump(match))


# ---------------------------------------------------------------------------
# disputes
# ---------------------------------------------------------------------------
@bp.post("/matches/<match_id>/disputes")
@endpoint("Coach")
def file_dispute(ctx, match_id):
    existing = find("match", match_id)
    if existing is not None:
        coach_participates(ctx, existing)
    match = must_find("match", match_id)
    filing_team_id = req_str(ctx.body, "filing_team_id")
    reason_code = req_enum(ctx.body, "dispute_reason_code", DISPUTE_REASONS)
    opt_str(ctx.body, "dispute_note", None, 1, 500)
    if match["result_status"] not in ("CONFIRMED", "ADJUDICATED"):
        fail("ERR_INVALID_MATCH_STATE", "Only a decided result may be disputed.")
    if match["dispute_status"] != "NONE":
        fail("ERR_INVALID_DISPUTE_STATE", "This match already carries a dispute.")
    if filing_team_id not in _participants(match):
        fail("ERR_TEAM_NOT_MATCH_PARTICIPANT", "The filing team does not play in this match.")
    deadline = match.get("dispute_deadline_at")
    if deadline is None or db.now > deadline:
        fail("ERR_DISPUTE_WINDOW_CLOSED", "The dispute window for this result has closed.")
    domain.update(
        match,
        dispute_status="OPEN",
        dispute_filed_by_team_id=filing_team_id,
        dispute_reason_code=reason_code,
    )
    touch(match)
    return ok(dump(match))


DISPUTE_FROM_STATE = {
    "ACCEPT_REVIEW": ("OPEN",),
    "REQUEST_INFO": ("UNDER_REVIEW",),
    "RESUME_REVIEW": ("NEEDS_INFO",),
    "UPHOLD": ("UNDER_REVIEW",),
    "REJECT": ("UNDER_REVIEW",),
}
DISPUTE_TO_STATE = {
    "ACCEPT_REVIEW": "UNDER_REVIEW",
    "REQUEST_INFO": "NEEDS_INFO",
    "RESUME_REVIEW": "UNDER_REVIEW",
    "UPHOLD": "UPHELD",
    "REJECT": "REJECTED",
}


def _flag_scholarships_stale(season):
    if season is None:
        return
    team_ids = set(t["id"] for t in domain.teams_of_season(season["id"]))
    for student in db.all("student"):
        if (
            student.get("showcase_status") == "NOMINATED"
            and student.get("nominating_team_id") in team_ids
            and student.get("scholarship_award_state") == "CURRENT"
        ):
            domain.update(student, scholarship_award_state="RECALC_REQUIRED")


@bp.post("/matches/<match_id>/dispute-actions")
@endpoint("LeagueAdmin")
def act_on_dispute(ctx, match_id):
    match = must_find("match", match_id)
    body = ctx.body
    action = req_enum(body, "action", tuple(DISPUTE_FROM_STATE))
    corrected_home = opt_int(body, "corrected_home_games_won", None, low=0)
    corrected_away = opt_int(body, "corrected_away_games_won", None, low=0)
    opt_str(body, "info_request_note", None, 1, 500)
    if action == "UPHOLD" and (corrected_home is None or corrected_away is None):
        fail("ERR_INVALID_REQUEST", "Upholding a dispute requires both corrected game counts.")
    if action == "REJECT" and (
        present(body, "corrected_home_games_won") or present(body, "corrected_away_games_won")
    ):
        fail("ERR_INVALID_REQUEST", "Rejecting a dispute forbids the corrected game counts.")
    if match["dispute_status"] not in DISPUTE_FROM_STATE[action]:
        fail("ERR_INVALID_DISPUTE_STATE", "That action is not available from the current state.")
    match["dispute_status"] = DISPUTE_TO_STATE[action]
    touch(match)
    if action == "UPHOLD":
        match["result_status"] = "ADJUDICATED"
        match["home_games_won"] = corrected_home
        match["away_games_won"] = corrected_away
        match["winner_team_id"] = _winner_from(match, corrected_home, corrected_away)
        domain.award_points(match)
        season = domain.season_of(match)
        domain.mark_all_seeded_stale(season)
        _flag_scholarships_stale(season)
    return ok(dump(match))


# ---------------------------------------------------------------------------
# broadcast control
# ---------------------------------------------------------------------------
BROADCAST_ACTIONS = ("REGISTER", "GO_LIVE", "RESUME", "END")
BROADCAST_WINDOW_FIELDS = ("broadcast_school_id", "broadcast_start_at", "broadcast_end_at")


@bp.post("/matches/<match_id>/broadcast")
@endpoint("Coach")
def control_broadcast(ctx, match_id):
    existing = find("match", match_id)
    if existing is not None:
        coach_participates(ctx, existing)
    match = must_find("match", match_id)
    body = ctx.body
    action = req_enum(body, "action", BROADCAST_ACTIONS)
    if action == "REGISTER":
        school_id = req_str(body, "broadcast_school_id")
        start_at = req_dt(body, "broadcast_start_at")
        end_at = req_dt(body, "broadcast_end_at")
    else:
        for field in BROADCAST_WINDOW_FIELDS:
            if present(body, field):
                fail("ERR_INVALID_REQUEST", "Field '%s' must be absent for this action." % field)
        school_id = None
        start_at = opt_dt(body, "broadcast_start_at")
        end_at = opt_dt(body, "broadcast_end_at")
    if action == "GO_LIVE" and match["play_status"] not in ("SERVER_READY", "PLAYED"):
        fail("ERR_INVALID_MATCH_STATE", "The match is not in a state that permits going live.")
    status = match["broadcast_status"]
    if action == "REGISTER" and status != "NONE":
        fail("ERR_INVALID_BROADCAST_STATE", "The channel has already been claimed.")
    if action == "GO_LIVE" and status != "SCHEDULED":
        fail("ERR_INVALID_BROADCAST_STATE", "Only a scheduled broadcast may go live.")
    if action == "RESUME" and (status != "SUSPENDED" or match["spectator_strikes"] >= 3):
        fail("ERR_INVALID_BROADCAST_STATE", "The broadcast cannot be resumed.")
    if action == "END" and status not in ("LIVE", "SUSPENDED"):
        fail("ERR_INVALID_BROADCAST_STATE", "Only a live or suspended broadcast may be ended.")
    if action == "REGISTER":
        own_school_ids = []
        for key in ("home_team_id", "away_team_id"):
            team = find("team", match[key])
            if team is not None and team["coach_id"] == ctx.user_id:
                own_school_ids.append(team["school_id"])
        if school_id not in own_school_ids:
            fail(
                "ERR_BROADCAST_SCHOOL_MISMATCH",
                "The broadcast school must be the acting coach's own school.",
            )
        school = find("school", school_id)
        if domain.broadcast_channel_conflict(school, start_at, end_at, match["id"]):
            fail("ERR_BROADCAST_CHANNEL_CONFLICT", "The school channel is already committed.")
        domain.update(
            match,
            broadcast_school_id=school_id,
            broadcast_start_at=start_at,
            broadcast_end_at=end_at,
            broadcast_status="SCHEDULED",
        )
    elif action == "GO_LIVE" or action == "RESUME":
        domain.update(match, broadcast_status="LIVE")
    else:
        domain.update(match, broadcast_status="ENDED")
    touch(match)
    return ok(dump(match))
