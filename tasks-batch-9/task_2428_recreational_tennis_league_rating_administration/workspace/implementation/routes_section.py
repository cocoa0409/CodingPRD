"""Logical clock, sections, facilities and the two year-end recalculation phases."""

from decimal import Decimal

from flask import Blueprint

import derive
from auth import authenticate
from credit import round3
from errors import ApiError
from response import empty_response, object_response
from routes_common import (ADMIN_ONLY, ALL_ROLES, ROLE_CAPTAIN, ROLE_LEAGUE_COORDINATOR,
                           ROLE_SECTION_ADMIN, found, listing, reference)
from store import db, insert, new_id, now_iso, public, set_clock, sorted_rows, touch
from validation import (body, opt_int, opt_enum, opt_string, reject_unknown, req_instant,
                        req_int, req_string, bad)

bp = Blueprint("section", __name__, url_prefix="/tennis")

FACILITY_READ_ROLES = (ROLE_SECTION_ADMIN, ROLE_LEAGUE_COORDINATOR, ROLE_CAPTAIN)
SECTION_LIST_ROLES = (ROLE_SECTION_ADMIN, ROLE_LEAGUE_COORDINATOR)
SURFACES = ("HARD", "CLAY", "INDOOR_HARD")

UP_THRESHOLD = Decimal("0.25")
DOWN_THRESHOLD = Decimal("-0.35")


@bp.post("/_clock/set_current_utc")
def set_clock_endpoint():
    authenticate(ADMIN_ONLY)
    payload = body()
    reject_unknown(payload, {"current_utc"})
    target = req_instant(payload, "current_utc")
    set_clock(target)
    return empty_response(200)


@bp.post("/sections")
def create_section():
    authenticate(ADMIN_ONLY)
    payload = body()
    reject_unknown(payload, {
        "code", "name", "season_year", "min_matches_for_playoff_eligibility", "strike_limit",
        "disqualification_strike_limit", "scorecard_submission_window_hours",
        "scorecard_dispute_window_hours", "grievance_window_hours"})
    code = req_string(payload, "code", 3, 32)
    name = req_string(payload, "name", 1)
    season_year = req_int(payload, "season_year", 2000, 2100)
    min_matches = opt_int(payload, "min_matches_for_playoff_eligibility", 3, 1)
    strike_limit = opt_int(payload, "strike_limit", 3, 1)
    disq_limit = opt_int(payload, "disqualification_strike_limit", 6, 1)
    submission_hours = opt_int(payload, "scorecard_submission_window_hours", 48, 0)
    dispute_hours = opt_int(payload, "scorecard_dispute_window_hours", 24, 0)
    grievance_hours = opt_int(payload, "grievance_window_hours", 72, 0)
    if disq_limit <= strike_limit:
        bad("disqualification_strike_limit must be strictly greater than strike_limit.")
    for existing in db.sections.values():
        if existing.get("code") == code:
            bad("Section code must be unique across sections.")

    record = {
        "id": new_id(),
        "code": code,
        "name": name,
        "season_year": season_year,
        "rating_period_status": "OPEN_SEASON",
        "recalc_run_index": 0,
        "min_matches_for_playoff_eligibility": min_matches,
        "strike_limit": strike_limit,
        "disqualification_strike_limit": disq_limit,
        "scorecard_submission_window_hours": submission_hours,
        "scorecard_dispute_window_hours": dispute_hours,
        "grievance_window_hours": grievance_hours,
        "recalculated_player_count": 0,
        "published_level_change_count": 0,
    }
    insert("sections", record)
    return object_response(public(record), 201)


@bp.get("/sections/<section_id>")
def get_section(section_id):
    authenticate(ALL_ROLES)
    return object_response(public(found("sections", section_id)))


@bp.get("/sections")
def list_sections():
    authenticate(SECTION_LIST_ROLES)
    spec = {"code": ("code", "str"), "season_year": ("season_year", "int"),
            "rating_period_status": ("rating_period_status", "str")}
    return listing(db.sections.values(), spec)


@bp.get("/sections/<section_id>/facilities")
def list_section_facilities(section_id):
    authenticate(FACILITY_READ_ROLES)
    found("sections", section_id)
    rows = [f for f in db.facilities.values() if f.get("section_id") == section_id]
    return listing(rows, {"surface": ("surface", "str")})


@bp.post("/facilities")
def create_facility():
    authenticate(ADMIN_ONLY)
    payload = body()
    raw_section = payload.get("section_id")
    if isinstance(raw_section, str) and raw_section.strip():
        section = reference("sections", raw_section.strip())
    else:
        section = None
    reject_unknown(payload, {"section_id", "name", "court_count", "turnaround_buffer_minutes",
                             "surface"})
    req_string(payload, "section_id", 1)
    name = req_string(payload, "name", 1)
    court_count = req_int(payload, "court_count", 1)
    buffer_minutes = opt_int(payload, "turnaround_buffer_minutes", 30, 0)
    surface = opt_enum(payload, "surface", SURFACES, "HARD")
    if section is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")

    record = {
        "id": new_id(),
        "section_id": section["id"],
        "name": name,
        "court_count": court_count,
        "turnaround_buffer_minutes": buffer_minutes,
        "surface": surface,
    }
    insert("facilities", record)
    return object_response(public(record), 201)


@bp.get("/facilities/<facility_id>")
def get_facility(facility_id):
    authenticate(FACILITY_READ_ROLES)
    return object_response(public(found("facilities", facility_id)))


# ------------------------------------------------- year-end recalculation ---

def _section_players(section_id):
    rows = [p for p in db.players.values() if p.get("section_id") == section_id]
    return sorted_rows(rows)


@bp.post("/sections/<section_id>/year-end-recalc")
def year_end_recalc(section_id):
    authenticate(ADMIN_ONLY)
    section = found("sections", section_id)
    payload = body()
    reject_unknown(payload, set())
    if section.get("rating_period_status") != "OPEN_SEASON":
        raise ApiError("ERR_RECALC_PHASE_INVALID")

    scope = [p for p in _section_players(section_id)
             if p.get("status") != "DISQUALIFIED" and (p.get("verified_line_count") or 0) >= 1]
    for player in scope:
        proposed_dynamic = derive.dynamic_rating(player["id"], "year_end")
        player["proposed_recalc_dynamic"] = float(proposed_dynamic) if proposed_dynamic is not None else None
        current = player.get("rating_level")
        if current is None or proposed_dynamic is None:
            player["proposed_recalc_level"] = current
        else:
            level = Decimal(str(current))
            delta = round3(proposed_dynamic - level)
            if delta >= UP_THRESHOLD:
                level = derive.clamp_level(level + Decimal("0.5"))
            elif delta <= DOWN_THRESHOLD:
                level = derive.clamp_level(level - Decimal("0.5"))
            player["proposed_recalc_level"] = float(level)
        touch(player)

    section["recalculated_player_count"] = len(scope)
    section["rating_period_status"] = "RECALC_IN_PROGRESS"
    touch(section)
    return object_response(public(section))


@bp.post("/sections/<section_id>/publish-recalc")
def publish_recalc(section_id):
    authenticate(ADMIN_ONLY)
    section = found("sections", section_id)
    payload = body()
    reject_unknown(payload, set())
    if section.get("rating_period_status") != "RECALC_IN_PROGRESS":
        raise ApiError("ERR_RECALC_PHASE_INVALID")

    scope = [p for p in _section_players(section_id) if p.get("proposed_recalc_level") is not None]
    changed_count = 0
    stamp = now_iso()
    for player in scope:
        proposed = player.get("proposed_recalc_level")
        if player.get("rating_level") != proposed:
            changed_count += 1
        player["rating_level"] = proposed
        player["rating_type"] = "COMPUTER_RATED"
        player["dynamic_rating"] = player.get("proposed_recalc_dynamic")
        derive.append_rating_history(player, "YEAR_END_RECALC", proposed,
                                     player.get("proposed_recalc_dynamic"),
                                     int(section.get("season_year") or 0) + 1, stamp)
        touch(player)
        new_level = Decimal(str(proposed)) if proposed is not None else None

        def below_band(team, level=new_level):
            if level is None:
                return False
            league = db.leagues.get(team.get("league_id")) or {}
            band = league.get("ntrp_level")
            return band is not None and Decimal(str(band)) < level

        derive.suspend_roster_spots(player, "YEAR_END_RECALC", None, below_band)

    section["published_level_change_count"] = changed_count
    section["rating_period_status"] = "RECALC_PUBLISHED"
    section["recalc_run_index"] = int(section.get("recalc_run_index") or 0) + 1
    touch(section)
    return object_response(public(section))
