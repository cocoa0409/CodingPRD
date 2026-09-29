"""League injury reporting and public designations (PRD §3.9)."""
from flask import Blueprint

import constants as C
import serializers as S
import validation as V
from db import db, sort_rows, stamp_new, touch
from errors import ApiError
from response import created, ok, ok_list, paginate, read_pagination
from services import audits as audit_service
from services import calc
from services import posture

bp = Blueprint("reports", __name__)


@bp.post("/injury-report-entries")
def file_report():
    actor = V.authenticate(["ClubComplianceOfficer"])
    b = V.body()
    game_id = V.req_id(b, "game_id")
    player_id = V.req_id(b, "player_id")
    practice_participation = V.req_enum(b, "practice_participation", C.PRACTICE_PARTICIPATION)
    designation = V.req_enum(b, "designation", C.DESIGNATIONS)

    game = V.get_game(game_id)
    player = V.get_player(player_id)
    V.officer_scope(actor, player["club_id"])
    if player["club_id"] not in (game["home_club_id"], game["away_club_id"]):
        raise ApiError("ERR_PLAYER_CLUB_MISMATCH")
    if db.now < game["report_window_opens_at"]:
        raise ApiError("ERR_REPORT_WINDOW_NOT_OPEN")
    if db.now >= game["kickoff_at"]:
        raise ApiError("ERR_REPORT_WINDOW_CLOSED")

    required = calc.resolve_public_designation(player["id"])
    if designation != required:
        raise ApiError("ERR_INJURY_DESIGNATION_MISMATCH")
    for existing in db.injury_report_entries.values():
        if existing["game_id"] == game["id"] and existing["player_id"] == player["id"]:
            raise ApiError("ERR_DUPLICATE_INJURY_REPORT")

    late = db.now >= game["report_window_closes_at"]
    row = {
        "game_id": game["id"],
        "player_id": player["id"],
        "club_id": player["club_id"],
        "practice_participation": practice_participation,
        "designation": designation,
        "required_designation": required,
        "filed_at": db.now,
        "amended_at": None,
        "amended_from_designation": None,
        "status": "LATE_FILED" if late else "FILED",
    }
    stamp_new(row)
    db.injury_report_entries[row["id"]] = row

    if late:
        audit_service.open_auto_issued_audit(
            player["club_id"], ["LATE_INJURY_REPORT"], exposure_days=0)
        club = db.clubs.get(player["club_id"])
        if club is not None:
            posture.propagate(club)

    return created(S.report_out(row))


@bp.post("/injury-report-entries/<row_id>/amend")
def amend_report(row_id):
    actor = V.authenticate(["ClubComplianceOfficer"])
    b = V.body()
    practice_participation = V.req_enum(b, "practice_participation", C.PRACTICE_PARTICIPATION)
    designation = V.req_enum(b, "designation", C.DESIGNATIONS)

    entry = V.get_report(row_id)
    V.officer_scope(actor, entry["club_id"])
    if entry["status"] not in ("FILED", "LATE_FILED"):
        raise ApiError("ERR_RESOURCE_STATE_INVALID",
                       message="Only a FILED or LATE_FILED entry may be amended.")
    game = db.games.get(entry["game_id"])
    if game is not None and db.now >= game["kickoff_at"]:
        raise ApiError("ERR_REPORT_WINDOW_CLOSED")

    required = calc.resolve_public_designation(entry["player_id"])
    if designation != required:
        raise ApiError("ERR_INJURY_DESIGNATION_MISMATCH")

    entry["amended_from_designation"] = entry["designation"]
    entry["practice_participation"] = practice_participation
    entry["designation"] = designation
    entry["required_designation"] = required
    entry["amended_at"] = db.now
    entry["status"] = "AMENDED"
    touch(entry)
    return ok(S.report_out(entry))


@bp.get("/injury-report-entries/<row_id>")
def get_report(row_id):
    actor = V.authenticate(C.ALL_ROLES)
    entry = V.get_report(row_id)
    V.role_identity(actor)
    return ok(S.report_out(entry))


@bp.get("/injury-report-entries")
def list_reports():
    actor = V.authenticate(C.ALL_ROLES)
    limit, offset = read_pagination()
    game_id = V.filter_str("game_id")
    player_id = V.filter_str("player_id")
    club_id = V.filter_str("club_id")
    status = V.filter_enum("status", C.REPORT_STATUSES)
    designation = V.filter_enum("designation", C.DESIGNATIONS)
    V.role_identity(actor)

    rows = sort_rows(list(db.injury_report_entries.values()))
    if game_id is not None:
        rows = [r for r in rows if r["game_id"] == game_id]
    if player_id is not None:
        rows = [r for r in rows if r["player_id"] == player_id]
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if designation is not None:
        rows = [r for r in rows if r["designation"] == designation]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.report_out(r) for r in page], limit, offset, total)
