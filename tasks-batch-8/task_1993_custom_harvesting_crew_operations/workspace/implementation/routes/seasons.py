"""HarvestSeason endpoints (§3.1, §3.8) and the logical clock."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_SEASON_NOT_DRAFT,
    ERR_SEASON_NOT_ACTIVE,
    ERR_SEASON_NOT_SETTLING,
    ERR_NO_COMBINE_AVAILABLE,
    ERR_STOPS_STILL_RUNNING,
    ERR_UNRESOLVED_SETTLEMENTS_EXIST,
    ERR_STALE_VERSION,
)
from helpers import (
    get_json_body,
    require_fields,
    require_type,
    is_int,
    stamp_new,
    touch,
    public,
    sort_key,
    get_season_or_404,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination, paginate
from services.domain import (
    skip_stop_cascade,
)

bp = Blueprint("seasons", __name__)

SEASON_STATUSES = ("DRAFT", "ACTIVE", "SETTLING", "CLOSED")


# ---------------------------------------------------------------------------
# Logical clock (§2.5)
# ---------------------------------------------------------------------------

@bp.route("/harvest/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("HarvestOperator")
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso8601 = require_type(body, "to_iso8601", "string")
    db.logical_clock_iso = to_iso8601
    return success_object({"current_utc": db.logical_clock_iso})


# ---------------------------------------------------------------------------
# HarvestSeason CRUD + lifecycle
# ---------------------------------------------------------------------------

@bp.route("/harvest/seasons", methods=["POST"])
def create_season():
    require_roles("HarvestOperator")
    body = get_json_body()
    require_fields(
        body,
        [
            "season_year",
            "diesel_baseline_per_gallon_cents",
            "current_diesel_per_gallon_cents",
        ],
    )
    season_year = require_type(body, "season_year", "int")
    baseline = require_type(body, "diesel_baseline_per_gallon_cents", "int")
    current = require_type(body, "current_diesel_per_gallon_cents", "int")

    record = stamp_new(
        {
            "season_year": season_year,
            "diesel_baseline_per_gallon_cents": baseline,
            "current_diesel_per_gallon_cents": current,
            "committed_acres_total": 0,
            "harvested_acres_total": 0,
            "status": "DRAFT",
        }
    )
    db.seasons[record["id"]] = record
    return success_object(public(record), status=201)


@bp.route("/harvest/seasons", methods=["GET"])
def list_seasons():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    items = sorted(db.seasons.values(), key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/seasons/<seasonId>", methods=["GET"])
def get_season(seasonId):
    require_roles(*ALL_ROLES)
    season = get_season_or_404(seasonId)
    return success_object(public(season))


@bp.route("/harvest/seasons/<seasonId>", methods=["PATCH"])
def patch_season(seasonId):
    require_roles("HarvestOperator")
    season = get_season_or_404(seasonId)
    # Diesel prices editable only while DRAFT or ACTIVE; frozen once the
    # season has moved on to SETTLING or CLOSED.
    if season["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            ERR_SEASON_NOT_ACTIVE,
            409,
            "Diesel prices are editable only while season is DRAFT or ACTIVE",
        )
    body = get_json_body()
    if "current_diesel_per_gallon_cents" in body and body["current_diesel_per_gallon_cents"] is not None:
        season["current_diesel_per_gallon_cents"] = require_type(
            body, "current_diesel_per_gallon_cents", "int"
        )
    if "diesel_baseline_per_gallon_cents" in body and body["diesel_baseline_per_gallon_cents"] is not None:
        season["diesel_baseline_per_gallon_cents"] = require_type(
            body, "diesel_baseline_per_gallon_cents", "int"
        )
    touch(season)
    return success_object(public(season))


@bp.route("/harvest/seasons/<seasonId>/activate", methods=["POST"])
def activate_season(seasonId):
    require_roles("HarvestOperator")
    season = get_season_or_404(seasonId)
    if season["status"] != "DRAFT":
        raise ApiError(ERR_SEASON_NOT_DRAFT, 409, "Season activation requires DRAFT")
    has_available_combine = any(
        m["season_id"] == season["id"]
        and m["machine_kind"] == "COMBINE"
        and m["status"] == "AVAILABLE"
        for m in db.machines.values()
    )
    if not has_available_combine:
        raise ApiError(
            ERR_NO_COMBINE_AVAILABLE,
            409,
            "Season activation requires at least one AVAILABLE COMBINE machine",
        )
    if (
        season["diesel_baseline_per_gallon_cents"] <= 0
        or season["current_diesel_per_gallon_cents"] <= 0
    ):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "diesel_baseline_per_gallon_cents and current_diesel_per_gallon_cents must both be > 0",
        )
    season["status"] = "ACTIVE"
    touch(season)
    return success_object(public(season))


@bp.route("/harvest/seasons/<seasonId>/open-settlement", methods=["POST"])
def open_settlement(seasonId):
    require_roles("HarvestOperator")
    season = get_season_or_404(seasonId)
    if season["status"] != "ACTIVE":
        raise ApiError(ERR_SEASON_NOT_ACTIVE, 409, "Operation requires season ACTIVE")
    running = any(
        s["season_id"] == season["id"]
        and s["status"] in ("EN_ROUTE", "CUTTING", "PAUSED_WEATHER")
        for s in db.route_stops.values()
    )
    if running:
        raise ApiError(
            ERR_STOPS_STILL_RUNNING,
            409,
            "open-settlement requires no stops in EN_ROUTE/CUTTING/PAUSED_WEATHER",
        )
    # Cascade: force-skip all still-SCHEDULED stops in this season.
    for s in list(db.route_stops.values()):
        if s["season_id"] == season["id"] and s["status"] == "SCHEDULED":
            skip_stop_cascade(s)
    season["status"] = "SETTLING"
    touch(season)
    return success_object(public(season))


@bp.route("/harvest/seasons/<seasonId>/close", methods=["POST"])
def close_season(seasonId):
    require_roles("HarvestOperator")
    season = get_season_or_404(seasonId)
    # State legality (priority 4)
    if season["status"] != "SETTLING":
        raise ApiError(ERR_SEASON_NOT_SETTLING, 409, "Operation requires season SETTLING")
    # Business rule: every settlement whose contract belongs to this season
    # must be PAID or RESOLVED.
    season_contract_ids = {
        c["id"] for c in db.contracts.values() if c["season_id"] == season["id"]
    }
    for st in db.settlements.values():
        if st["contract_id"] in season_contract_ids and st["status"] not in (
            "PAID",
            "RESOLVED",
        ):
            raise ApiError(
                ERR_UNRESOLVED_SETTLEMENTS_EXIST,
                409,
                "close requires every settlement PAID or RESOLVED",
            )
    # OCC (priority 12): expected_season_version must match current version.
    body = get_json_body()
    require_fields(body, ["expected_season_version"])
    if not is_int(body["expected_season_version"]):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "expected_season_version must be an integer"
        )
    if body["expected_season_version"] != season["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_season_version does not match the season's current version",
        )
    # Side effects: machines → RETIRED; ACTIVE crew → RELEASED.
    for m in db.machines.values():
        if m["season_id"] == season["id"] and m["status"] != "RETIRED":
            m["status"] = "RETIRED"
            touch(m)
    for c in db.crew_members.values():
        if c["season_id"] == season["id"] and c["status"] == "ACTIVE":
            c["status"] = "RELEASED"
            touch(c)
    season["status"] = "CLOSED"
    touch(season)
    return success_object(public(season))
