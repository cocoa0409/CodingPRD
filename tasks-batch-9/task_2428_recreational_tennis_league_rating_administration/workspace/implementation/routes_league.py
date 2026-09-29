"""Leagues: creation, reads and the standings table."""

from decimal import Decimal

from flask import Blueprint, request

import credit
from auth import authenticate
from errors import ApiError
from response import object_response, paginate
from routes_common import (ADMIN_ONLY, ALL_ROLES, apply_filters, found, listing, reference)
from store import db, insert, new_id, public, sorted_rows
from validation import (bad, body, check_level, opt_bool, opt_int, reject_unknown, req_enum,
                        req_instant, req_level)
import routes_league_lifecycle as lifecycle

bp = Blueprint("league", __name__, url_prefix="/tennis")
bp.register_blueprint(lifecycle.bp)

TIERS = ("LOCAL", "DISTRICT", "SECTION")
AGE_GROUPS = ("AGE_18_OVER", "AGE_40_OVER", "AGE_55_OVER")
FORMATS = ("MENS_DOUBLES", "WOMENS_DOUBLES", "MIXED_DOUBLES")
PARENT_TIER = {"LOCAL": "DISTRICT", "DISTRICT": "SECTION"}

LEAGUE_FIELDS = {
    "section_id", "parent_league_id", "tier", "ntrp_level", "age_group", "format",
    "lines_per_match", "min_active_roster_size", "max_roster_size", "min_playoff_eligible_players",
    "max_teams", "advancement_slots", "match_duration_minutes", "allow_same_day_doubleheader",
    "registration_opens_at", "registration_closes_at", "roster_lock_at", "season_end_at",
}


@bp.post("/leagues")
def create_league():
    authenticate(ADMIN_ONLY)
    payload = body()

    raw_section = payload.get("section_id")
    section = None
    if isinstance(raw_section, str) and raw_section.strip():
        section = reference("sections", raw_section.strip())
    raw_parent = payload.get("parent_league_id")
    parent = None
    if isinstance(raw_parent, str) and raw_parent.strip():
        parent = reference("leagues", raw_parent.strip())
        if section is not None and parent.get("section_id") != section["id"]:
            raise ApiError("ERR_SECTION_SCOPE_MISMATCH")

    reject_unknown(payload, LEAGUE_FIELDS)
    if section is None and not isinstance(raw_section, str):
        bad("Field 'section_id' is required.")
    tier = req_enum(payload, "tier", TIERS)
    ntrp_level = req_level(payload, "ntrp_level")
    age_group = req_enum(payload, "age_group", AGE_GROUPS)
    fmt = req_enum(payload, "format", FORMATS)
    lines_per_match = opt_int(payload, "lines_per_match", 3, 3, 5)
    if lines_per_match % 2 == 0:
        bad("Field 'lines_per_match' must be an odd integer between 3 and 5.")
    min_active = opt_int(payload, "min_active_roster_size", 8, 1)
    max_roster = opt_int(payload, "max_roster_size", 14, 1)
    min_eligible = opt_int(payload, "min_playoff_eligible_players", 6, 0)
    max_teams = opt_int(payload, "max_teams", 8, 1)
    advancement_slots = opt_int(payload, "advancement_slots", 1, 0)
    duration = opt_int(payload, "match_duration_minutes", 180, 1)
    doubleheader = opt_bool(payload, "allow_same_day_doubleheader", False)
    opens_at = req_instant(payload, "registration_opens_at")
    closes_at = req_instant(payload, "registration_closes_at")
    roster_lock_at = req_instant(payload, "roster_lock_at")
    season_end_at = req_instant(payload, "season_end_at")
    if not closes_at > opens_at:
        bad("registration_closes_at must be strictly after registration_opens_at.")
    if roster_lock_at < closes_at:
        bad("roster_lock_at must be at or after registration_closes_at.")
    if not season_end_at > roster_lock_at:
        bad("season_end_at must be strictly after roster_lock_at.")
    if section is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    check_level(ntrp_level)
    _check_ladder(tier, parent, raw_parent, section, ntrp_level, age_group, fmt)

    record = {
        "id": new_id(),
        "section_id": section["id"],
        "parent_league_id": parent["id"] if parent else None,
        "tier": tier,
        "ntrp_level": float(ntrp_level),
        "age_group": age_group,
        "format": fmt,
        "lines_per_match": lines_per_match,
        "min_active_roster_size": min_active,
        "max_roster_size": max_roster,
        "min_playoff_eligible_players": min_eligible,
        "max_teams": max_teams,
        "advancement_slots": advancement_slots,
        "match_duration_minutes": duration,
        "allow_same_day_doubleheader": doubleheader,
        "registration_opens_at": payload["registration_opens_at"],
        "registration_closes_at": payload["registration_closes_at"],
        "roster_lock_at": payload["roster_lock_at"],
        "season_end_at": payload["season_end_at"],
        "status": "DRAFT",
        "registered_team_count": 0,
        "noncompliant_team_count": 0,
        "finalized_match_count": 0,
        "seeded_team_count": 0,
    }
    insert("leagues", record)
    return object_response(public(record), 201)


def _check_ladder(tier, parent, raw_parent, section, ntrp_level, age_group, fmt):
    if tier == "SECTION":
        if raw_parent is not None:
            raise ApiError("ERR_LEAGUE_LADDER_INVALID")
        return
    if parent is None:
        raise ApiError("ERR_LEAGUE_LADDER_INVALID")
    if parent.get("section_id") != section["id"]:
        raise ApiError("ERR_LEAGUE_LADDER_INVALID")
    if parent.get("tier") != PARENT_TIER.get(tier):
        raise ApiError("ERR_LEAGUE_LADDER_INVALID")
    if Decimal(str(parent.get("ntrp_level"))) != ntrp_level:
        raise ApiError("ERR_LEAGUE_LADDER_INVALID")
    if parent.get("age_group") != age_group or parent.get("format") != fmt:
        raise ApiError("ERR_LEAGUE_LADDER_INVALID")


@bp.get("/leagues/<league_id>")
def get_league(league_id):
    authenticate(ALL_ROLES)
    return object_response(public(found("leagues", league_id)))


@bp.get("/leagues")
def list_leagues():
    authenticate(ALL_ROLES)
    spec = {"section_id": ("section_id", "str"), "parent_league_id": ("parent_league_id", "str"),
            "tier": ("tier", "str"), "ntrp_level": ("ntrp_level", "level"),
            "age_group": ("age_group", "str"), "format": ("format", "str"),
            "status": ("status", "str")}
    rows = list(db.leagues.values())
    raw_level = request.args.get("ntrp_level")
    if raw_level not in (None, ""):
        try:
            wanted = float(raw_level)
        except ValueError:
            rows = []
        else:
            rows = [r for r in rows if r.get("ntrp_level") == wanted]
    spec.pop("ntrp_level")
    rows = apply_filters(rows, spec)
    return paginate(sorted_rows(rows), public)


@bp.get("/leagues/<league_id>/standings")
def league_standings(league_id):
    authenticate(ALL_ROLES)
    league = found("leagues", league_id)
    basis = request.args.get("basis") or "official"
    if basis not in ("official", "provisional"):
        bad("Query parameter 'basis' must be 'official' or 'provisional'.")

    views = []
    for team in db.teams.values():
        if team.get("league_id") != league_id:
            continue
        view = dict(team)
        if basis == "provisional":
            view.update(credit.standings_figures(team, "provisional"))
        views.append(view)
    ordered = credit.rank_candidates(views)
    return paginate(ordered, public)
