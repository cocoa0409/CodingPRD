"""Irrigation schedules: budget gate, half-open overlap, meter reconciliation.

Create gate order follows PRD section 3.9 (a refining section):
season accepting -> window inside season -> zone overlap -> water budget ->
OCC (tier 17, last per section 2.6).
"""
from flask import Blueprint, request

import db
import services
from app_util import body
from errors import err, err_forbidden_role, err_invalid_request, err_not_found, err_state, err_stale_version
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import pagination_args, parse_dt, req_int, req_str, require_field

bp = Blueprint("irrigation", __name__)

STAFF = ["GardenAdmin", "Coordinator"]
IRRIGATION_TARGETS = {"CANCELLED", "RECONCILED"}


def _get_schedule(schedule_id):
    sched = db.irrigations.get(schedule_id)
    if sched is None:
        raise err_not_found("irrigation")
    return sched


def _overlaps(season_id: str, zone: str, start, end) -> bool:
    """Half-open [start, end) conflict against occupied same-season same-zone schedules."""
    for other in db.irrigations.values():
        if other["season_id"] != season_id or other["zone"] != zone:
            continue
        if other["status"] not in services.IRRIGATION_OCCUPIED:
            continue
        if start < other["planned_end_at"] and other["planned_start_at"] < end:
            return True
    return False


@bp.post("/api/irrigation-schedules")
def create_schedule():
    ctx = require_auth()
    require_role(ctx, STAFF)
    data = body()
    # existence (tier 3)
    season_id = require_field(data, "season_id")
    season = db.seasons.get(season_id)
    if season is None:
        raise err_not_found("season")
    # shape (tier 5)
    zone = req_str(data, "zone")
    start = parse_dt(require_field(data, "planned_start_at"), "planned_start_at")
    end = parse_dt(require_field(data, "planned_end_at"), "planned_end_at")
    if end <= start:
        raise err_invalid_request("planned_end_at must be strictly after planned_start_at")
    planned = req_int(data, "planned_gallons")
    if planned <= 0:
        raise err_invalid_request("planned_gallons must be > 0")
    expected = req_int(data, "expected_season_version")
    # --- PRD 3.9 workflow gate sequence ---
    if season["status"] not in {"PLANTING", "GROWING", "HARVESTING"}:
        raise err("ERR_SEASON_NOT_ACCEPTING", "season is not accepting irrigation schedules")
    if start < season["season_starts_at"] or end > season["season_ends_at"]:
        raise err("ERR_OUTSIDE_SEASON_WINDOW", "window lies outside the season operating window")
    if _overlaps(season_id, zone, start, end):
        raise err("ERR_IRRIGATION_OVERLAP", "window overlaps an occupied schedule in this zone")
    committed, actual = services.season_water(season_id)
    if committed + actual + planned > season["water_budget_gallons"]:
        raise err("ERR_WATER_BUDGET_EXCEEDED", "projected water use exceeds the season budget")
    # OCC (tier 17)
    if expected != season["version"]:
        raise err_stale_version()
    rec = services.create_record({
        "season_id": season_id,
        "zone": zone,
        "planned_start_at": start,
        "planned_end_at": end,
        "planned_gallons": planned,
        "gallons_actual": None,
        "status": "SCHEDULED",
    })
    db.irrigations[rec["id"]] = rec
    services.bump(season)
    return ok(services.irrigation_view(rec), status=201)


@bp.get("/api/irrigation-schedules")
def list_schedules():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.irrigations.values(),
        {"season_id": "season_id", "zone": "zone", "status": "status"},
        request.args, services.irrigation_view,
    )
    total = len(items)
    return ok([services.irrigation_view(s) for s in items[offset:offset + limit]],
              pagination=(limit, offset, total))


@bp.get("/api/irrigation-schedules/<scheduleId>")
def get_schedule(scheduleId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.irrigation_view(_get_schedule(scheduleId)))


@bp.post("/api/irrigation-schedules/<scheduleId>/log-meter")
def log_meter(scheduleId):
    ctx = require_auth()
    require_role(ctx, STAFF)
    sched = _get_schedule(scheduleId)
    data = body()
    gallons = data.get("gallons_actual")
    if isinstance(gallons, bool) or not isinstance(gallons, int):
        raise err_invalid_request("gallons_actual must be an integer")
    if gallons < 0:
        raise err("ERR_QUANTITY_INVALID", "gallons_actual must be >= 0")
    if sched["status"] not in {"SCHEDULED", "DUE", "MISSED"}:
        raise err_state("IRRIGATION")
    sched["gallons_actual"] = gallons
    sched["status"] = "LOGGED"
    services.bump(sched)
    season = db.seasons.get(sched["season_id"])
    if season is not None:
        services.bump(season)
    return ok(services.irrigation_view(sched))


@bp.post("/api/irrigation-schedules/<scheduleId>/transition")
def transition_schedule(scheduleId):
    ctx = require_auth()
    require_role(ctx, STAFF)
    sched = _get_schedule(scheduleId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in IRRIGATION_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(IRRIGATION_TARGETS)}")
    # per-transition actors: RECONCILED is GardenAdmin-only
    if to_state == "RECONCILED" and ctx.role != "GardenAdmin":
        raise err_forbidden_role()

    if to_state == "CANCELLED":
        if sched["status"] not in {"SCHEDULED", "DUE"}:
            raise err_state("IRRIGATION")
        sched["status"] = "CANCELLED"
        services.bump(sched)
        season = db.seasons.get(sched["season_id"])
        if season is not None:
            services.bump(season)

    elif to_state == "RECONCILED":
        if sched["status"] != "LOGGED":
            raise err_state("IRRIGATION")
        sched["status"] = "RECONCILED"
        services.bump(sched)

    return ok(services.irrigation_view(sched))
