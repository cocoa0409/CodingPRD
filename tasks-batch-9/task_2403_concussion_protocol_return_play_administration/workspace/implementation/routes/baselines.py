"""Baseline neurocognitive testing (PRD §3.2)."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import serializers as S
import validation as V
from db import db, sort_rows, stamp_new, touch
from errors import ApiError
from response import created, ok, ok_list, paginate, read_pagination
from services import calc

bp = Blueprint("baselines", __name__)


@bp.post("/baseline-tests")
def file_baseline():
    actor = V.authenticate(["ClubPhysician"])
    b = V.body()
    player_id = V.req_id(b, "player_id")
    season_year = V.req_int(b, "season_year", 2020, 2100)
    composite_score = V.req_int(b, "composite_score", 0, 100)
    reaction_time_ms = V.req_int(b, "reaction_time_ms", 200, 1500)
    symptom_score = V.req_int(b, "symptom_score", 0, 20)
    expected_player_version = V.req_int(b, "expected_player_version", 0)

    player = V.get_player(player_id)
    clinician = V.role_identity(actor)
    V.physician_scope(actor, player["club_id"])
    V.not_suspended(clinician)
    if player["version"] != expected_player_version:
        raise ApiError("ERR_STALE_PLAYER_VERSION")
    V.credential_valid(clinician)

    for existing in calc.player_baselines(player["id"]):
        if existing["status"] == "VALID":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = {
        "player_id": player["id"],
        "administered_by_clinician_id": clinician["id"],
        "season_year": season_year,
        "composite_score": composite_score,
        "reaction_time_ms": reaction_time_ms,
        "symptom_score": symptom_score,
        "administered_at": db.now,
        "validity_expires_at": db.now + timedelta(days=C.BASELINE_VALIDITY_DAYS),
        "status": "VALID",
        "retest_required_reason": "NONE",
    }
    stamp_new(row)
    db.baseline_tests[row["id"]] = row

    player["baseline_status"] = calc.resolve_baseline_status(player["id"])
    touch(player)

    return created(S.baseline_out(row))


@bp.post("/baseline-tests/<row_id>/invalidate")
def invalidate_baseline(row_id):
    V.authenticate(["LeagueAdmin"])
    b = V.body()
    V.req_str(b, "reason")
    test = V.get_baseline(row_id)
    if test["status"] != "VALID":
        raise ApiError("ERR_RESOURCE_STATE_INVALID",
                       message="Only a VALID baseline test may be invalidated.")

    test["status"] = "INVALIDATED"
    test["retest_required_reason"] = "ADMIN_INVALIDATION"
    touch(test)

    player = db.players.get(test["player_id"])
    if player is not None:
        player["baseline_status"] = calc.resolve_baseline_status(player["id"])
        touch(player)

    return ok(S.baseline_out(test))


@bp.get("/baseline-tests/<row_id>")
def get_baseline(row_id):
    actor = V.authenticate(C.ALL_ROLES)
    test = V.get_baseline(row_id)
    V.role_identity(actor)
    return ok(S.baseline_out(test))


@bp.get("/baseline-tests")
def list_baselines():
    actor = V.authenticate(C.ALL_ROLES)
    limit, offset = read_pagination()
    player_id = V.filter_str("player_id")
    clinician_id = V.filter_str("administered_by_clinician_id")
    season_year = V.filter_int("season_year")
    status = V.filter_enum("status", C.BASELINE_TEST_STATUSES)
    V.role_identity(actor)

    rows = sort_rows(list(db.baseline_tests.values()))
    if player_id is not None:
        rows = [r for r in rows if r["player_id"] == player_id]
    if clinician_id is not None:
        rows = [r for r in rows if r["administered_by_clinician_id"] == clinician_id]
    if season_year is not None:
        rows = [r for r in rows if r["season_year"] == season_year]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([S.baseline_out(r) for r in page], limit, offset, total)
