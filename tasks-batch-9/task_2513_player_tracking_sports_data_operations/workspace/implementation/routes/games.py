"""Games, the two collection dimensions, certification and normalization runs
(PRD §3.4, §3.6, §3.9)."""

from flask import Blueprint

import db
from auth import authenticate
from calc import (MAPPING_VERSION, METRIC_CODES, NORMALIZATION_BASES,
                  QUALITY_INDEX_FLOOR, TRACKING_GENERATIONS,
                  league_reserve_minutes, normalized_tracking_metric)
from db import audit_new, new_id, store, touch
from errors import ApiError
from lookups import require_club, require_game, require_venue
from response import array_response, object_response
from services.quality import recompute_quality_index
from util import F, num, serialize, serialize_many, sorted_rows
from validation import (field, no_body, paginate, pagination, string_filter,
                        validate_body)

bp = Blueprint("games", __name__)

GAME_SPEC = {
    "venue_id": field("string"),
    "home_club_id": field("string"),
    "away_club_id": field("string"),
    "scheduled_start_utc": field("datetime"),
    "tracking_generation": field("enum", values=TRACKING_GENERATIONS),
    "licensable_minutes": field("integer", minimum=1),
}

NORMALIZATION_SPEC = {
    "basis": field("enum", values=NORMALIZATION_BASES),
    "metric_code": field("enum", values=METRIC_CODES),
    # An empty array passes the schema check on purpose (PRD §2.10 rank 4), so
    # that the domain refusal at rank 38 survives to reach the caller.
    "segment_values": field("array", item=field("number", minimum=0)),
}

READ_GAME_ROLES = ("LeagueDataOps", "Statistician", "QualityReviewer",
                   "ClubDataOfficer", "Licensee")


# --------------------------------------------------------------------------
# Scheduling
# --------------------------------------------------------------------------

@bp.post("/games")
def create_game():
    authenticate("LeagueDataOps")
    body = validate_body(GAME_SPEC)
    require_venue(body["venue_id"])
    require_club(body["home_club_id"])
    require_club(body["away_club_id"])

    licensable = body["licensable_minutes"]
    reserve = league_reserve_minutes(licensable)
    net = licensable - reserve

    game = {
        "id": new_id(),
        "venue_id": body["venue_id"],
        "home_club_id": body["home_club_id"],
        "away_club_id": body["away_club_id"],
        "scheduled_start_utc": body["scheduled_start_utc"],
        "tracking_generation": body["tracking_generation"],
        "licensable_minutes": licensable,
        "collection_status": "SCHEDULED",
        "certification_status": "PENDING",
        "data_quality_flag": "CLEAN",
        "draft_tag_count": 0,
        "submitted_tag_count": 0,
        "accepted_tag_count": 0,
        "under_correction_tag_count": 0,
        "superseded_tag_count": 0,
        "total_tag_count": 0,
        "approved_correction_count": 0,
        "rejected_correction_count": 0,
        "masked_tag_count": 0,
        "quality_index": 0.0,
        "league_reserve_minutes": reserve,
        "net_allocatable_minutes": net,
        "allocated_minutes_total": 0,
        "remaining_allocatable_minutes": net,
        "league_reserve_allocated_minutes": 0,
        "certified_at_utc": None,
    }
    audit_new(game)
    store.games[game["id"]] = game
    return object_response(serialize(game), 201)


@bp.get("/games/<game_id>")
def get_game(game_id):
    authenticate(*READ_GAME_ROLES)
    game = require_game(game_id)
    return object_response(serialize(game))


@bp.get("/games")
def list_games():
    authenticate(*READ_GAME_ROLES)
    limit, offset = pagination()
    venue_id = string_filter("venue_id")
    home_club_id = string_filter("home_club_id")
    away_club_id = string_filter("away_club_id")
    collection_status = string_filter("collection_status")

    rows = list(store.games.values())
    if venue_id is not None:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    if home_club_id is not None:
        rows = [r for r in rows if r["home_club_id"] == home_club_id]
    if away_club_id is not None:
        rows = [r for r in rows if r["away_club_id"] == away_club_id]
    if collection_status is not None:
        rows = [r for r in rows if r["collection_status"] == collection_status]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)


# --------------------------------------------------------------------------
# Collection dimension
# --------------------------------------------------------------------------

def _require_certified_venue(game):
    """Rank 20: the single hard link from the calibration subsystem."""
    venue = store.venues.get(game["venue_id"])
    if venue is None or venue["data_posture"] != "CERTIFIED":
        raise ApiError("ERR_VENUE_NOT_CERTIFIED",
                       "The hosting venue's data_posture is not CERTIFIED.")


@bp.post("/games/<game_id>/open-collection")
def open_collection(game_id):
    authenticate("LeagueDataOps")
    game = require_game(game_id)
    no_body()

    # rank 13 then rank 20
    if game["collection_status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_GAME_COLLECTION_STATE",
                       "Collection may only be opened from SCHEDULED.")
    _require_certified_venue(game)

    game["collection_status"] = "LIVE"
    game["data_quality_flag"] = "CLEAN"
    touch(game)
    return object_response(serialize(game))


@bp.post("/games/<game_id>/close-collection")
def close_collection(game_id):
    authenticate("LeagueDataOps")
    game = require_game(game_id)
    no_body()

    if game["collection_status"] != "LIVE":
        raise ApiError("ERR_INVALID_GAME_COLLECTION_STATE",
                       "Collection may only be closed from LIVE.")

    game["collection_status"] = "COLLECTED"

    # There is no longer a live stream to consume; post-game sessions untouched.
    for session in sorted_rows(db.sessions_of_game(game["id"])):
        if session["status"] != "ACTIVE":
            continue
        if session["delivery_mode"] != "REALTIME":
            continue
        session["status"] = "SUSPENDED"
        session["halt_reason"] = "CLIENT_REQUEST"
        touch(session)

    recompute_quality_index(game)
    touch(game)
    return object_response(serialize(game))


@bp.post("/games/<game_id>/resume-collection")
def resume_collection(game_id):
    authenticate("LeagueDataOps")
    game = require_game(game_id)
    no_body()

    if game["collection_status"] != "SUSPENDED_COLLECTION":
        raise ApiError("ERR_INVALID_GAME_COLLECTION_STATE",
                       "Collection may only be resumed from SUSPENDED_COLLECTION.")
    _require_certified_venue(game)

    game["collection_status"] = "LIVE"
    game["data_quality_flag"] = "CLEAN"

    # Reactivate precisely those sessions the degradation paused — a consent
    # loss or an SLA circuit breaker is deliberately left where it is.
    for session in sorted_rows(db.sessions_of_game(game["id"])):
        if session["status"] != "SUSPENDED":
            continue
        if session["halt_reason"] != "VENUE_DEGRADED":
            continue
        session["status"] = "ACTIVE"
        session["halt_reason"] = None
        touch(session)

    touch(game)
    return object_response(serialize(game))


@bp.post("/games/<game_id>/certify")
def certify_game(game_id):
    authenticate("LeagueDataOps")
    game = require_game(game_id)
    no_body()

    # rank 12: ARCHIVED is accepted on purpose — the first passage to OFFICIAL
    # archives the game, so every re-certification cycle runs against an
    # already-ARCHIVED row.
    if game["collection_status"] not in ("COLLECTED", "ARCHIVED"):
        raise ApiError("ERR_GAME_NOT_COLLECTED",
                       "The game's collection must be COLLECTED or ARCHIVED.")

    # rank 14
    if game["certification_status"] == "OFFICIAL":
        raise ApiError("ERR_GAME_ALREADY_OFFICIAL",
                       "The game's statistical record is already OFFICIAL.")

    # rank 35
    if game["under_correction_tag_count"] != 0:
        raise ApiError("ERR_OPEN_CORRECTIONS",
                       "A correction request is still unresolved on this game.")

    # rank 36 — a game still in PENDING lands here rather than at rank 14
    if game["accepted_tag_count"] < 1:
        raise ApiError("ERR_NO_ACCEPTED_TAGS",
                       "The game carries no accepted event tags.")

    # rank 37
    if F(game["quality_index"]) < F(QUALITY_INDEX_FLOOR):
        raise ApiError("ERR_QUALITY_INDEX_BELOW_THRESHOLD",
                       "The game's quality_index is below %s."
                       % QUALITY_INDEX_FLOOR)

    game["certification_status"] = "OFFICIAL"
    game["certified_at_utc"] = store.clock_raw
    if game["collection_status"] == "COLLECTED":
        game["collection_status"] = "ARCHIVED"
    touch(game)
    return object_response(serialize(game))


# --------------------------------------------------------------------------
# Normalization runs
# --------------------------------------------------------------------------

@bp.post("/games/<game_id>/normalization-runs")
def create_normalization_run(game_id):
    authenticate("LeagueDataOps")
    game = require_game(game_id)
    body = validate_body(NORMALIZATION_SPEC)

    # rank 12
    if game["collection_status"] not in ("COLLECTED", "ARCHIVED"):
        raise ApiError("ERR_GAME_NOT_COLLECTED",
                       "Normalization requires a COLLECTED or ARCHIVED game.")

    # rank 38 — the deliberate special case
    if len(body["segment_values"]) == 0:
        raise ApiError("ERR_NORMALIZATION_SEGMENTS_EMPTY",
                       "segment_values must not be empty.")

    generation = game["tracking_generation"]
    scale, drift_pct, normalized = normalized_tracking_metric(
        body["basis"], generation, body["segment_values"])

    run = {
        "id": new_id(),
        "game_id": game["id"],
        "basis": body["basis"],
        "metric_code": body["metric_code"],
        "segment_values": body["segment_values"],
        "source_generation": generation,
        "scale_factor_applied": num(scale),
        "drift_correction_pct": num(drift_pct),
        "mapping_version": MAPPING_VERSION,
        "normalized_value": num(normalized),
    }
    audit_new(run)
    store.normalization_runs[run["id"]] = run
    return object_response(serialize(run), 201)


@bp.get("/games/<game_id>/normalization-runs")
def list_normalization_runs(game_id):
    authenticate("LeagueDataOps", "ClubDataOfficer")
    require_game(game_id)
    limit, offset = pagination()
    basis = string_filter("basis")
    metric_code = string_filter("metric_code")
    rows = db.normalization_runs_of_game(game_id)
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    if metric_code is not None:
        rows = [r for r in rows if r["metric_code"] == metric_code]
    rows = sorted_rows(rows)
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many(page), limit, offset, total)
