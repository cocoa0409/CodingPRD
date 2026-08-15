"""Fleet administration: vessels, season rates, geo zones, maintenance
windows, weather advisories (PRD §3.1, §3.2)."""

from flask import Blueprint

import common
import db
import errors
import response
from middleware import require_roles
from services import booking_ops, pricing

bp = Blueprint("fleet", __name__)

ALL_ROLES = ("Renter", "DockStaff", "FleetManager", "Mechanic")


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------

@bp.post("/vessels")
@require_roles("FleetManager")
def create_vessel(user_id, role):
    body = common.json_body()
    name = common.as_str(common.req_field(body, "name"), "name")
    size_class = common.as_enum(
        common.req_field(body, "size_class"), "size_class", pricing.SIZE_CLASSES
    )
    berth_count = common.as_int(common.req_field(body, "berth_count"), "berth_count")
    home_marina = common.as_str(common.req_field(body, "home_marina"), "home_marina")
    capacity = common.as_int(
        common.req_field(body, "fuel_tank_capacity_gallons"), "fuel_tank_capacity_gallons"
    )
    if capacity <= 0:
        errors.err(errors.ERR_INVALID_REQUEST, "fuel_tank_capacity_gallons must be > 0")

    rec = db.base_record()
    rec.update({
        "name": name,
        "size_class": size_class,
        "berth_count": berth_count,
        "home_marina": home_marina,
        "fuel_tank_capacity_gallons": capacity,
        "status": "AVAILABLE",
    })
    db.insert("vessels", rec)
    return response.ok(common.vessel_out(rec), status=201)


@bp.get("/vessels/<vid>")
@require_roles(*ALL_ROLES)
def get_vessel(vid, user_id, role):
    vessel = db.get("vessels", vid)
    if vessel is None:
        errors.err(errors.ERR_NOT_FOUND, f"Vessel {vid} does not exist")
    return response.ok(common.vessel_out(vessel))


# ---------------------------------------------------------------------------
# Season rates
# ---------------------------------------------------------------------------

@bp.post("/season-rates")
@require_roles("FleetManager")
def create_season_rate(user_id, role):
    body = common.json_body()
    size_class = common.as_enum(
        common.req_field(body, "size_class"), "size_class", pricing.SIZE_CLASSES
    )
    season = common.as_enum(common.req_field(body, "season"), "season", pricing.SEASONS)
    start_date = common.parse_date(common.req_field(body, "start_date"), "start_date")
    end_date = common.parse_date(common.req_field(body, "end_date"), "end_date")
    nightly = common.as_int(
        common.req_field(body, "nightly_rate_cents"), "nightly_rate_cents"
    )
    discount_pct = common.as_int(
        common.req_field(body, "weekly_discount_pct"), "weekly_discount_pct"
    )
    if end_date < start_date:
        errors.err(errors.ERR_INVALID_REQUEST, "end_date must not precede start_date")
    if nightly <= 0:
        errors.err(errors.ERR_INVALID_REQUEST, "nightly_rate_cents must be > 0")
    if discount_pct < 0 or discount_pct > 50:
        errors.err(
            errors.ERR_INVALID_REQUEST, "weekly_discount_pct must be between 0 and 50"
        )

    # Closed-interval overlap with any existing rate of the same size class;
    # touching endpoints conflict.
    for r in db.all_of("season_rates"):
        if r["size_class"] != size_class:
            continue
        if r["start_date"] <= end_date and r["end_date"] >= start_date:
            errors.err(
                errors.ERR_SEASON_RATE_OVERLAP,
                "Rate window overlaps an existing window of the same size class",
            )

    rec = db.base_record()
    rec.update({
        "size_class": size_class,
        "season": season,
        "start_date": start_date,
        "end_date": end_date,
        "nightly_rate_cents": nightly,
        "weekly_discount_pct": discount_pct,
    })
    db.insert("season_rates", rec)
    return response.ok(common.season_rate_out(rec), status=201)


# ---------------------------------------------------------------------------
# Geo zones
# ---------------------------------------------------------------------------

@bp.post("/geo-zones")
@require_roles("FleetManager")
def create_geo_zone(user_id, role):
    body = common.json_body()
    zone_code = common.as_str(common.req_field(body, "zone_code"), "zone_code")
    name = common.as_str(common.req_field(body, "name"), "name")
    max_vessels = common.as_int(
        common.req_field(body, "max_vessels_per_night"), "max_vessels_per_night"
    )
    allowed = common.as_list(
        common.req_field(body, "allowed_size_classes"), "allowed_size_classes"
    )
    for member in allowed:
        common.as_enum(member, "allowed_size_classes", pricing.SIZE_CLASSES)
    if max_vessels < 1:
        errors.err(errors.ERR_INVALID_REQUEST, "max_vessels_per_night must be >= 1")
    for z in db.all_of("geo_zones"):
        if z["zone_code"] == zone_code:
            errors.err(errors.ERR_INVALID_REQUEST, f"zone_code {zone_code} already exists")

    rec = db.base_record()
    rec.update({
        "zone_code": zone_code,
        "name": name,
        "max_vessels_per_night": max_vessels,
        "allowed_size_classes": list(allowed),
    })
    db.insert("geo_zones", rec)
    return response.ok(common.geo_zone_out(rec), status=201)


# ---------------------------------------------------------------------------
# Maintenance windows
# ---------------------------------------------------------------------------

@bp.post("/vessels/<vid>/maintenance-windows")
@require_roles("FleetManager")
def create_maintenance_window(vid, user_id, role):
    vessel = db.get("vessels", vid)
    if vessel is None:
        errors.err(errors.ERR_NOT_FOUND, f"Vessel {vid} does not exist")
    body = common.json_body()
    start_date = common.parse_date(common.req_field(body, "start_date"), "start_date")
    end_date = common.parse_date(common.req_field(body, "end_date"), "end_date")
    reason = common.opt_field(body, "reason")
    if reason is not None and not isinstance(reason, str):
        errors.err(errors.ERR_INVALID_REQUEST, "reason must be a string")
    if end_date < start_date:
        errors.err(errors.ERR_INVALID_REQUEST, "end_date must not precede start_date")

    # Closed-interval conflicts: blocking bookings and other windows of the
    # same vessel; touching endpoints count as conflict.
    if booking_ops.window_conflict_with_blocking_bookings(vid, start_date, end_date):
        errors.err(
            errors.ERR_MAINTENANCE_DATE_CONFLICT,
            "Window conflicts with a booking of the vessel",
        )
    if booking_ops.maintenance_conflict_exists(vid, start_date, end_date):
        errors.err(
            errors.ERR_MAINTENANCE_DATE_CONFLICT,
            "Window overlaps another maintenance window of the vessel",
        )

    today = db.current_date()
    born_in_progress = start_date <= today <= end_date
    rec = db.base_record()
    rec.update({
        "vessel_id": vid,
        "start_date": start_date,
        "end_date": end_date,
        "reason": reason,
        "source": "SCHEDULED_PLANNED",
        "status": "IN_PROGRESS" if born_in_progress else "SCHEDULED",
    })
    db.insert("maintenance_windows", rec)
    if born_in_progress and vessel["status"] == "AVAILABLE":
        vessel["status"] = "IN_MAINTENANCE"
        db.touch(vessel)
    return response.ok(common.maintenance_window_out(rec), status=201)


@bp.get("/vessels/<vid>/maintenance-windows")
@require_roles(*ALL_ROLES)
def list_maintenance_windows(vid, user_id, role):
    vessel = db.get("vessels", vid)
    if vessel is None:
        errors.err(errors.ERR_NOT_FOUND, f"Vessel {vid} does not exist")
    windows = [w for w in db.all_of("maintenance_windows") if w["vessel_id"] == vid]
    page, total, limit, offset = common.paginate(windows)
    return response.list_ok(
        [common.maintenance_window_out(w) for w in page], total, limit, offset
    )


# ---------------------------------------------------------------------------
# Weather advisories
# ---------------------------------------------------------------------------

@bp.post("/weather-advisories")
@require_roles("FleetManager")
def create_weather_advisory(user_id, role):
    body = common.json_body()
    zone_ids = common.opt_field(body, "zone_ids")
    # Priority 4: every referenced zone must exist.
    if isinstance(zone_ids, list):
        for zid in zone_ids:
            if isinstance(zid, str) and db.get("geo_zones", zid) is None:
                errors.err(errors.ERR_NOT_FOUND, f"GeoZone {zid} does not exist")
    severity = common.as_enum(
        common.req_field(body, "severity"), "severity", ("WATCH", "WARNING", "STORM")
    )
    zone_ids = common.as_list(common.req_field(body, "zone_ids"), "zone_ids")
    if len(zone_ids) == 0:
        errors.err(errors.ERR_INVALID_REQUEST, "zone_ids must be non-empty")
    for zid in zone_ids:
        common.as_str(zid, "zone_ids")
    window_start = common.parse_datetime(
        common.req_field(body, "window_start"), "window_start"
    )
    window_end = common.parse_datetime(common.req_field(body, "window_end"), "window_end")
    if window_end <= window_start:
        errors.err(errors.ERR_INVALID_REQUEST, "window_end must be after window_start")

    rec = db.base_record()
    rec.update({
        "severity": severity,
        "zone_ids": list(zone_ids),
        "window_start": window_start,
        "window_end": window_end,
        "status": "ACTIVE",
    })
    db.insert("weather_advisories", rec)
    return response.ok(common.weather_advisory_out(rec), status=201)
