"""Window sanity, harvest-window overlap, station capacity, and
frost-versus-flood water-conflict checks (validation bands 7 and 8)."""
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from db import store
from errors import ApiError
from validation import to_decimal

FLOOD_LEAD_HOURS = 24


def season_window_bounds(season):
    """Inclusive harvest dates as a half-open datetime continuum:
    [harvest_window_startT00:00Z, (harvest_window_end + 1 day)T00:00Z)."""
    start = datetime.combine(season["_window_start_date"], time.min, tzinfo=timezone.utc)
    end_excl = datetime.combine(season["_window_end_date"] + timedelta(days=1),
                                time.min, tzinfo=timezone.utc)
    return start, end_excl


def check_window_sanity(window_start, window_end):
    if not (window_start < window_end):
        raise ApiError("ERR_INVALID_WINDOW", 422, "window_start must be strictly before window_end")


def check_window_within_season(season, window_start, window_end):
    start, end_excl = season_window_bounds(season)
    if window_start < start or window_end > end_excl:
        raise ApiError("ERR_WINDOW_OUTSIDE_SEASON", 422,
                       "Harvest window lies outside the season harvest window")


def check_date_within_season(season, scheduled_date):
    if scheduled_date < season["_window_start_date"] or scheduled_date > season["_window_end_date"]:
        raise ApiError("ERR_WINDOW_OUTSIDE_SEASON", 422,
                       "scheduled_date lies outside the season harvest window")


def check_harvest_overlap(bog_id, window_start, window_end, exclude_id=None):
    """Half-open interval conflict against REQUESTED/APPROVED tickets on the bog.
    Adjacency (one window's end equal to the other's start) is not a conflict."""
    for t in store.tickets.values():
        if t["bog_id"] != bog_id or t["status"] not in ("REQUESTED", "APPROVED"):
            continue
        if exclude_id is not None and t["id"] == exclude_id:
            continue
        if t["window_start"] < window_end and window_start < t["window_end"]:
            raise ApiError("ERR_HARVEST_WINDOW_OVERLAP", 409,
                           "Harvest window overlaps another live ticket on this bog")


def check_station_capacity(station, scheduled_date, expected_barrels):
    """Aggregate day load over SCHEDULED/RECEIVED deliveries; exactly equal is allowed."""
    day_load = Decimal("0")
    for d in store.deliveries.values():
        if (d["receiving_station_id"] == station["id"]
                and d["scheduled_date"] == scheduled_date
                and d["status"] in ("SCHEDULED", "RECEIVED")):
            day_load += to_decimal(d["expected_barrels"])
    if day_load + to_decimal(expected_barrels) > to_decimal(station["daily_capacity_barrels"]):
        raise ApiError("ERR_STATION_CAPACITY_EXCEEDED", 409,
                       "Station daily capacity would be exceeded")


def check_water_conflict(bog_id, frost_start, frost_end):
    """A frost event conflicts with any WET ticket's flood interval
    [ticket.window_start - 24h, ticket.window_end) in REQUESTED/APPROVED."""
    for t in store.tickets.values():
        if t["bog_id"] != bog_id or t["method"] != "WET":
            continue
        if t["status"] not in ("REQUESTED", "APPROVED"):
            continue
        flood_start = t["window_start"] - timedelta(hours=FLOOD_LEAD_HOURS)
        if flood_start < frost_end and frost_start < t["window_end"]:
            raise ApiError("ERR_WATER_SCHEDULE_CONFLICT", 409,
                           "Frost window intersects a wet-harvest flood interval")
