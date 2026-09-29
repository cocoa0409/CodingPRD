"""Clubs, clinicians, players and games (PRD §3.1)."""
import re
from datetime import timedelta

from flask import Blueprint

import constants as C
import serializers as S
import validation as V
from db import db, sort_rows, stamp_new, touch
from errors import ApiError
from response import created, ok, ok_list, paginate, read_pagination
from services import calc

bp = Blueprint("reference", __name__)

MARKET_CODE_RE = re.compile(r"^[A-Z]{3}$")


# --------------------------------------------------------------------- clubs
@bp.post("/clubs")
def create_club():
    V.authenticate(["LeagueAdmin"])
    b = V.body()
    name = V.req_str(b, "name", min_len=1, max_len=80)
    market_code = V.req_str(b, "market_code")
    if not MARKET_CODE_RE.match(market_code):
        V.bad("market_code must be exactly three uppercase letters.")
    slots = V.opt_int(b, "exemption_slots_total", 1, 5, default=C.DEFAULT_EXEMPTION_SLOTS_TOTAL)

    for existing in db.clubs.values():
        if existing["market_code"] == market_code:
            raise ApiError("ERR_UNIQUENESS_VIOLATION",
                           message="market_code is already registered.")

    row = {
        "name": name,
        "market_code": market_code,
        "exemption_slots_total": slots,
        "compliance_score": 100,
        "adjudicated_compliance_score": 100,
        "escalation_tier": "TIER_0",
        "status": "ACTIVE",
        "outstanding_fine_cents": 0,
        "open_violation_count": 0,
    }
    stamp_new(row)
    db.clubs[row["id"]] = row
    return created(S.club_out(row))


@bp.get("/clubs/<row_id>")
def get_club(row_id):
    actor = V.authenticate(C.ALL_ROLES)
    club = V.get_club(row_id)
    V.role_identity(actor)
    return ok(S.club_out(club))


@bp.get("/clubs/<row_id>/players")
def list_club_players(row_id):
    actor = V.authenticate(C.ALL_ROLES)
    limit, offset = read_pagination()
    availability = V.filter_enum("availability_status", C.AVAILABILITY_STATUSES)
    baseline = V.filter_enum("baseline_status", C.BASELINE_STATUSES)
    club = V.get_club(row_id)
    V.role_identity(actor)

    rows = [p for p in sort_rows(list(db.players.values())) if p["club_id"] == club["id"]]
    if availability is not None:
        rows = [p for p in rows if p["availability_status"] == availability]
    if baseline is not None:
        rows = [p for p in rows if p["baseline_status"] == baseline]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.player_out(p) for p in page], limit, offset, total)


@bp.get("/clubs/<row_id>/compliance-summary")
def club_compliance_summary(row_id):
    V.authenticate(["LeagueAdmin", "LeagueAuditor", "ClubComplianceOfficer"])
    club = V.get_club(row_id)
    return ok(S.compliance_summary_out(club))


# ----------------------------------------------------------------- clinicians
@bp.post("/clinicians")
def create_clinician():
    V.authenticate(["LeagueAdmin"])
    b = V.body()
    full_name = V.req_str(b, "full_name")
    affiliation = V.req_enum(b, "affiliation", C.AFFILIATIONS)
    license_number = V.req_str(b, "license_number")
    credential_expires_at = V.req_dt(b, "credential_expires_at")
    club_id = V.opt_id(b, "club_id")
    if affiliation == "CLUB_AFFILIATED":
        if club_id is None:
            V.bad("club_id is required when affiliation is CLUB_AFFILIATED.")
    elif club_id is not None:
        V.bad("club_id must be omitted unless affiliation is CLUB_AFFILIATED.")

    if club_id is not None:
        V.get_club(club_id)

    for existing in db.clinicians.values():
        if existing["license_number"] == license_number:
            raise ApiError("ERR_UNIQUENESS_VIOLATION",
                           message="license_number is already registered.")

    row = {
        "full_name": full_name,
        "affiliation": affiliation,
        "club_id": club_id,
        "license_number": license_number,
        "credential_expires_at": credential_expires_at,
        "status": "ACTIVE",
        "suspension_reason": None,
        "cases_cleared_count": 0,
    }
    stamp_new(row)
    db.clinicians[row["id"]] = row
    return created(S.clinician_out(row))


@bp.post("/clinicians/<row_id>/suspend")
def suspend_clinician(row_id):
    V.authenticate(["LeagueAdmin"])
    b = V.body()
    reason = V.req_str(b, "reason")
    clinician = V.get_clinician(row_id)
    if clinician["status"] != "ACTIVE":
        raise ApiError("ERR_CLINICIAN_SUSPENDED",
                       message="The clinician is already suspended.")

    clinician["status"] = "SUSPENDED"
    clinician["suspension_reason"] = reason
    touch(clinician)

    for clearance in sort_rows(list(db.inc_clearances.values())):
        if clearance["status"] != "PENDING":
            continue
        if clearance["inc_clinician_id"] != clinician["id"]:
            continue
        clearance["status"] = "SUPERSEDED"
        touch(clearance)
        case = db.concussion_cases.get(clearance["case_id"])
        if case is not None and case["case_status"] == "PENDING_INC_CLEARANCE":
            case["case_status"] = "RTP_IN_PROGRESS"
            touch(case)

    return ok(S.clinician_out(clinician))


@bp.get("/clinicians/<row_id>")
def get_clinician(row_id):
    actor = V.authenticate(C.ALL_ROLES)
    clinician = V.get_clinician(row_id)
    V.role_identity(actor)
    return ok(S.clinician_out(clinician))


@bp.get("/clinicians")
def list_clinicians():
    actor = V.authenticate(C.ALL_ROLES)
    limit, offset = read_pagination()
    club_id = V.filter_str("club_id")
    affiliation = V.filter_enum("affiliation", C.AFFILIATIONS)
    status = V.filter_enum("status", C.CLINICIAN_STATUSES)
    V.role_identity(actor)

    rows = sort_rows(list(db.clinicians.values()))
    if club_id is not None:
        rows = [r for r in rows if r.get("club_id") == club_id]
    if affiliation is not None:
        rows = [r for r in rows if r["affiliation"] == affiliation]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.clinician_out(r) for r in page], limit, offset, total)


# -------------------------------------------------------------------- players
@bp.post("/players")
def create_player():
    actor = V.authenticate(["LeagueAdmin", "ClubComplianceOfficer"])
    b = V.body()
    club_id = V.req_id(b, "club_id")
    full_name = V.req_str(b, "full_name")
    jersey_number = V.req_int(b, "jersey_number", 0, 99)
    position = V.req_enum(b, "position", C.POSITIONS)

    club = V.get_club(club_id)
    V.officer_scope(actor, club["id"])

    for existing in db.players.values():
        if existing["club_id"] == club["id"] and existing["jersey_number"] == jersey_number:
            raise ApiError("ERR_UNIQUENESS_VIOLATION",
                           message="jersey_number is already used inside this club.")

    row = {
        "club_id": club["id"],
        "full_name": full_name,
        "jersey_number": jersey_number,
        "position": position,
        "baseline_status": "NONE",
        "availability_status": "AVAILABLE",
    }
    stamp_new(row)
    db.players[row["id"]] = row
    return created(S.player_out(row))


@bp.get("/players/<row_id>")
def get_player(row_id):
    actor = V.authenticate(C.ALL_ROLES)
    player = V.get_player(row_id)
    V.role_identity(actor)
    return ok(S.player_out(player))


@bp.get("/players")
def list_players():
    actor = V.authenticate(C.ALL_ROLES)
    limit, offset = read_pagination()
    club_id = V.filter_str("club_id")
    availability = V.filter_enum("availability_status", C.AVAILABILITY_STATUSES)
    baseline = V.filter_enum("baseline_status", C.BASELINE_STATUSES)
    designation = V.filter_enum("public_injury_designation", C.DESIGNATIONS)
    V.role_identity(actor)

    rows = sort_rows(list(db.players.values()))
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if availability is not None:
        rows = [r for r in rows if r["availability_status"] == availability]
    if baseline is not None:
        rows = [r for r in rows if r["baseline_status"] == baseline]
    if designation is not None:
        rows = [r for r in rows if calc.resolve_public_designation(r["id"]) == designation]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.player_out(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------- games
@bp.post("/games")
def create_game():
    V.authenticate(["LeagueAdmin"])
    b = V.body()
    season_year = V.req_int(b, "season_year", 2020, 2100)
    week_index = V.req_int(b, "week_index", 1, 18)
    home_club_id = V.req_id(b, "home_club_id")
    away_club_id = V.req_id(b, "away_club_id")
    kickoff_at = V.req_dt(b, "kickoff_at")
    if home_club_id == away_club_id:
        V.bad("home_club_id and away_club_id must differ.")

    V.get_club(home_club_id)
    V.get_club(away_club_id)

    row = {
        "season_year": season_year,
        "week_index": week_index,
        "home_club_id": home_club_id,
        "away_club_id": away_club_id,
        "kickoff_at": kickoff_at,
        "status": "SCHEDULED",
        "report_window_opens_at": kickoff_at - timedelta(
            hours=C.REPORT_WINDOW_OPEN_HOURS_BEFORE_KICKOFF),
        "report_window_closes_at": kickoff_at - timedelta(
            minutes=C.REPORT_WINDOW_LATE_MINUTES_BEFORE_KICKOFF),
    }
    stamp_new(row)
    db.games[row["id"]] = row
    return created(S.game_out(row))


@bp.post("/games/<row_id>/advance-status")
def advance_game(row_id):
    V.authenticate(["LeagueAdmin"])
    b = V.body()
    to_status = V.req_enum(b, "to_status", C.GAME_STATUSES)
    game = V.get_game(row_id)

    allowed = {"SCHEDULED": "IN_PROGRESS", "IN_PROGRESS": "FINAL"}
    if allowed.get(game["status"]) != to_status:
        raise ApiError("ERR_RESOURCE_STATE_INVALID",
                       message="A game may only advance SCHEDULED -> IN_PROGRESS -> FINAL.")
    game["status"] = to_status
    touch(game)
    return ok(S.game_out(game))


@bp.get("/games/<row_id>")
def get_game(row_id):
    actor = V.authenticate(C.ALL_ROLES)
    game = V.get_game(row_id)
    V.role_identity(actor)
    return ok(S.game_out(game))


@bp.get("/games")
def list_games():
    actor = V.authenticate(C.ALL_ROLES)
    limit, offset = read_pagination()
    season_year = V.filter_int("season_year")
    week_index = V.filter_int("week_index")
    home_club_id = V.filter_str("home_club_id")
    away_club_id = V.filter_str("away_club_id")
    status = V.filter_enum("status", C.GAME_STATUSES)
    V.role_identity(actor)

    rows = sort_rows(list(db.games.values()))
    if season_year is not None:
        rows = [r for r in rows if r["season_year"] == season_year]
    if week_index is not None:
        rows = [r for r in rows if r["week_index"] == week_index]
    if home_club_id is not None:
        rows = [r for r in rows if r["home_club_id"] == home_club_id]
    if away_club_id is not None:
        rows = [r for r in rows if r["away_club_id"] == away_club_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.game_out(r) for r in page], limit, offset, total)
