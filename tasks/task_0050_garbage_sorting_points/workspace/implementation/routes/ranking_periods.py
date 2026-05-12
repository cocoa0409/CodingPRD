"""RankingPeriod endpoints: create, close, publish, list, read."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from db import db
from errors import (
    ERR_INVALID_STATE,
    ERR_RANKING_EMPTY,
    ERR_RANKING_PERIOD_NOT_ENDED,
    ERR_RANKING_PERIOD_OVERLAP,
    ERR_VALIDATION,
    raise_api_error,
)
from middleware import require_roles
from response import list_response, success_response
from services.calculations import compute_leaderboard
from services.common import (
    check_version,
    get_json_body,
    iso_z,
    paginate,
    parse_iso8601_utc,
    parse_pagination,
    require_datetime,
    require_enum,
)
from services.ledger import append_audit_log
from services.lookup import get_community, get_ranking_period

bp = Blueprint("ranking_periods", __name__)

GRANULARITIES = {"WEEKLY", "MONTHLY", "YEARLY"}
DIMENSIONS = {"HOUSEHOLD", "BUILDING", "COMMUNITY"}


@bp.post("/communities/<community_id>/ranking-periods")
@require_roles("CommunityAdmin")
def create_period(community_id: str):
    get_community(community_id)
    body = get_json_body()
    granularity = require_enum(body, "granularity", GRANULARITIES)
    dimension = require_enum(body, "dimension", DIMENSIONS)
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    if window_end <= window_start:
        raise_api_error(ERR_VALIDATION, "window_end must be > window_start.")

    # Validate overlap / contiguity within same (community_id, granularity, dimension)
    siblings = [
        p
        for p in db.ranking_periods.values()
        if p["community_id"] == community_id
        and p["granularity"] == granularity
        and p["dimension"] == dimension
    ]
    for p in siblings:
        ws = parse_iso8601_utc(p["window_start"])
        we = parse_iso8601_utc(p["window_end"])
        # Half-open overlap: [a, b) overlaps [c, d) iff a < d AND c < b
        if window_start < we and ws < window_end:
            raise_api_error(ERR_RANKING_PERIOD_OVERLAP, "Period overlaps an existing period.")

    if granularity in ("WEEKLY", "MONTHLY"):
        # Must be contiguous with the latest prior period (if any exists)
        priors = [
            p for p in siblings if parse_iso8601_utc(p["window_end"]) <= window_start
        ]
        if priors:
            last = max(priors, key=lambda x: parse_iso8601_utc(x["window_end"]))
            if parse_iso8601_utc(last["window_end"]) != window_start:
                raise_api_error(
                    ERR_RANKING_PERIOD_OVERLAP,
                    "Period must be contiguous with the prior period (window_start == prior.window_end).",
                )

    obj = {
        "community_id": community_id,
        "granularity": granularity,
        "dimension": dimension,
        "window_start": iso_z(window_start),
        "window_end": iso_z(window_end),
        "status": "OPEN",
        "published_at": None,
        "leaderboard": [],
    }
    db.stamp_create(obj)
    db.ranking_periods[obj["id"]] = obj
    return jsonify(success_response(obj)), 201


@bp.post("/communities/<community_id>/ranking-periods/<period_id>/close")
@require_roles("CommunityAdmin")
def close_period(community_id: str, period_id: str):
    period = get_ranking_period(community_id, period_id)
    body = get_json_body()
    check_version(body, period)
    if period["status"] != "OPEN":
        raise_api_error(ERR_INVALID_STATE, "Period must be OPEN to close.")
    if db.now() < parse_iso8601_utc(period["window_end"]):
        raise_api_error(ERR_RANKING_PERIOD_NOT_ENDED, "Window has not ended yet.")

    leaderboard = compute_leaderboard(period)
    period["leaderboard"] = leaderboard
    period["status"] = "CLOSED"
    db.stamp_update(period)
    return jsonify(success_response(period)), 200


@bp.post("/communities/<community_id>/ranking-periods/<period_id>/publish")
@require_roles("CommunityAdmin")
def publish_period(community_id: str, period_id: str):
    period = get_ranking_period(community_id, period_id)
    body = get_json_body()
    check_version(body, period)
    if period["status"] != "CLOSED":
        raise_api_error(ERR_INVALID_STATE, "Period must be CLOSED to publish.")
    if not period.get("leaderboard"):
        raise_api_error(ERR_RANKING_EMPTY, "Leaderboard is empty.")
    period["status"] = "PUBLISHED"
    period["published_at"] = db.now_iso()
    db.stamp_update(period)
    append_audit_log(
        actor_role=g.user_role,
        actor_id=g.user_id,
        action="RANKING_PUBLISHED",
        subject_kind="RANKING_PERIOD",
        subject_id=period["id"],
        before={"status": "CLOSED"},
        after={"status": "PUBLISHED", "published_at": period["published_at"]},
        reason=None,
    )
    return jsonify(success_response(period)), 200


@bp.get("/communities/<community_id>/ranking-periods/<period_id>")
@require_roles("CommunityAdmin", "Resident")
def read_period(community_id: str, period_id: str):
    p = get_ranking_period(community_id, period_id)
    return jsonify(success_response(p)), 200


@bp.get("/communities/<community_id>/ranking-periods")
@require_roles("CommunityAdmin", "Resident")
def list_periods(community_id: str):
    get_community(community_id)
    limit, offset = parse_pagination()
    granularity = request.args.get("granularity")
    dimension = request.args.get("dimension")
    status = request.args.get("status")
    items = [
        p
        for p in db.ranking_periods.values()
        if p["community_id"] == community_id
        and (granularity is None or p["granularity"] == granularity)
        and (dimension is None or p["dimension"] == dimension)
        and (status is None or p["status"] == status)
    ]
    items.sort(key=lambda x: x["created_at"])
    page, total = paginate(items, limit, offset)
    return jsonify(list_response(page, limit, offset, total)), 200
