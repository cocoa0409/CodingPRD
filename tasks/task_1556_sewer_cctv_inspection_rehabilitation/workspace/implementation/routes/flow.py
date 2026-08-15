"""FlowMonitoringPeriod endpoints."""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request

import db
from db import _parse_iso, _format_iso
from middleware import get_actor, require_roles
from response import success_object, success_list
from errors import err_invalid_request, err_invalid_state, err_not_found, err_conflict
from services.common import (
    body, require_string, require_number, require_enum, parse_datetime_field,
    parse_pagination, paginate, get_district, get_flow_period, sweep_notice_expiry,
)

bp = Blueprint("flow", __name__)

PHASES = {"PRE_REHAB", "POST_REHAB"}
MIN_DURATION_HOURS = 168


def period_view(p):
    return {
        "id": p["id"],
        "district_id": p["district_id"],
        "basin_label": p["basin_label"],
        "phase": p["phase"],
        "window_start": p["window_start"],
        "window_end": p["window_end"],
        "dry_weather_avg_gpm": p["dry_weather_avg_gpm"],
        "peak_storm_gpm": p["peak_storm_gpm"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/sewer/districts/<id>/flow-periods")
def create_period(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    district = get_district(id)
    payload = body()
    basin_label = require_string(payload, "basin_label")
    phase = require_enum(payload, "phase", PHASES)
    ws = parse_datetime_field(payload, "window_start", required=True)
    we = parse_datetime_field(payload, "window_end", required=True)
    if not (we > ws):
        raise err_invalid_request("window_end must be after window_start")
    ent = {
        "id": db.new_id(),
        "district_id": district["id"],
        "basin_label": basin_label,
        "phase": phase,
        "window_start": _format_iso(ws),
        "window_end": _format_iso(we),
        "dry_weather_avg_gpm": None,
        "peak_storm_gpm": None,
        "status": "DRAFT",
    }
    db.stamp_new(ent)
    db.flow_periods[ent["id"]] = ent
    sweep_notice_expiry()
    return success_object(period_view(ent), status=201)


@bp.get("/sewer/flow-periods/<id>")
def get_period_route(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    p = get_flow_period(id)
    return success_object(period_view(p))


@bp.get("/sewer/districts/<id>/flow-periods")
def list_periods(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    district = get_district(id)
    limit, offset = parse_pagination()
    items = [p for p in db.flow_periods.values() if p["district_id"] == district["id"]]
    ph = request.args.get("phase")
    if ph:
        items = [p for p in items if p["phase"] == ph]
    st = request.args.get("status")
    if st:
        items = [p for p in items if p["status"] == st]
    page, total = paginate(items, limit, offset)
    return success_list([period_view(p) for p in page], limit, offset, total)


@bp.post("/sewer/flow-periods/<id>/activate")
def activate_period(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    p = get_flow_period(id)
    if p["status"] != "DRAFT":
        raise err_invalid_state("period not DRAFT")
    ws = _parse_iso(p["window_start"])
    we = _parse_iso(p["window_end"])
    duration_hours = (we - ws).total_seconds() / 3600.0
    if duration_hours < MIN_DURATION_HOURS:
        raise err_conflict("ERR_MONITORING_TOO_SHORT", "window must be at least 168 hours")
    # conflict: same district+basin ACTIVE periods, closed-interval intersection (inclusive endpoints)
    for other in db.flow_periods.values():
        if other["id"] == p["id"]:
            continue
        if other["district_id"] != p["district_id"]:
            continue
        if other["basin_label"] != p["basin_label"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        ows = _parse_iso(other["window_start"])
        owe = _parse_iso(other["window_end"])
        # closed-interval intersection
        if ws <= owe and ows <= we:
            raise err_conflict("ERR_FLOW_WINDOW_CONFLICT", "another ACTIVE period overlaps")
    if p["phase"] == "POST_REHAB":
        has_rehab = any(
            s["district_id"] == p["district_id"] and s["rehab_status"] in ("REHABILITATED", "WARRANTY")
            for s in db.segments.values()
        )
        if not has_rehab:
            raise err_conflict("ERR_NO_REHAB_YET", "POST_REHAB requires a rehabilitated segment")
    p["status"] = "ACTIVE"
    db.touch(p)
    sweep_notice_expiry()
    return success_object(period_view(p))


@bp.post("/sewer/flow-periods/<id>/close")
def close_period(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    p = get_flow_period(id)
    if p["status"] != "ACTIVE":
        raise err_invalid_state("period not ACTIVE")
    payload = body()
    dry = payload.get("dry_weather_avg_gpm")
    peak = payload.get("peak_storm_gpm")
    if dry is None or peak is None:
        raise err_conflict("ERR_FLOW_DATA_MISSING", "dry_weather_avg_gpm and peak_storm_gpm required")
    for name, v in (("dry_weather_avg_gpm", dry), ("peak_storm_gpm", peak)):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise err_invalid_request(f"{name} must be a number")
    p["dry_weather_avg_gpm"] = dry
    p["peak_storm_gpm"] = peak
    p["status"] = "CLOSED"
    db.touch(p)
    sweep_notice_expiry()
    return success_object(period_view(p))


@bp.post("/sewer/flow-periods/<id>/analyze")
def analyze_period(id):
    actor = get_actor()
    require_roles(actor, ["DistrictEngineer"])
    p = get_flow_period(id)
    if p["status"] != "CLOSED":
        raise err_invalid_state("period not CLOSED")
    district = db.districts[p["district_id"]]
    if p["phase"] == "POST_REHAB":
        # find baseline: PRE_REHAB, same basin, CLOSED/ANALYZED, greatest window_end, tie latest created_at
        candidates = [
            q for q in db.flow_periods.values()
            if q["district_id"] == p["district_id"]
            and q["basin_label"] == p["basin_label"]
            and q["phase"] == "PRE_REHAB"
            and q["status"] in ("CLOSED", "ANALYZED")
            and q["dry_weather_avg_gpm"] is not None
            and q["peak_storm_gpm"] is not None
        ]
        if not candidates:
            raise err_conflict("ERR_NO_BASELINE", "no CLOSED/ANALYZED PRE_REHAB baseline for basin")
        candidates.sort(key=lambda q: (q["window_end"], q["created_at"]), reverse=True)
        baseline = candidates[0]
        pre_dry = Decimal(str(baseline["dry_weather_avg_gpm"]))
        post_dry = Decimal(str(p["dry_weather_avg_gpm"]))
        pre_storm = Decimal(str(baseline["peak_storm_gpm"]))
        post_storm = Decimal(str(p["peak_storm_gpm"]))
        if pre_dry == 0 or pre_storm == 0:
            raise err_invalid_request("baseline flow data invalid")
        dry_red = (Decimal(100) * (Decimal(1) - post_dry / pre_dry)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        storm_red = (Decimal(100) * (Decimal(1) - post_storm / pre_storm)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        basin_target_met = dry_red >= Decimal(str(district["ii_reduction_target_pct"]))
        p["status"] = "ANALYZED"
        db.touch(p)
        result = {
            "dry_weather_reduction_pct": float(dry_red),
            "storm_event_reduction_pct": float(storm_red),
            "basin_target_met": bool(basin_target_met),
        }
        sweep_notice_expiry()
        return success_object(result)
    else:
        # PRE_REHAB analyze: no baseline needed; just transition with empty analysis
        p["status"] = "ANALYZED"
        db.touch(p)
        result = {
            "dry_weather_reduction_pct": None,
            "storm_event_reduction_pct": None,
            "basin_target_met": None,
        }
        sweep_notice_expiry()
        return success_object(result)
