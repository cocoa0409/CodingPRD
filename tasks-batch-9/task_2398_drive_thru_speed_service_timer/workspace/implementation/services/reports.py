"""report_attainment_metrics + coaching_pool_points (PRD §3.8)."""

from decimal import Decimal

from constants import (
    ABANDON_PENALTY_SECONDS,
    BAND_POINTS,
    REMAKE_POINT_PENALTY,
    VOLUME_POINTS_CAP,
    VOLUME_POINTS_DIVISOR,
)
from db import db, dec, rhu, rhu_int, seconds_between, sorted_rows
from services.rollup import lookup_band

ONE = Decimal("1")


def input_loops(restaurant_id, window_start_at, window_end_at, variant):
    rows = []
    for loop in db.timer_loops.values():
        if loop["restaurant_id"] != restaurant_id:
            continue
        if variant == "PROVISIONAL":
            if loop["timing_state"] != "CLOSED":
                continue
            if loop["accuracy_state"] == "REMAKE_OPEN":
                continue
            anchor = loop["depart_at"]
        else:
            if loop["timing_state"] not in ("CLOSED", "ABANDONED"):
                continue
            anchor = loop["arrive_at"]
        if anchor is None:
            continue
        if window_start_at <= anchor < window_end_at:
            rows.append(loop)
    return sorted_rows(rows)


def loop_metric(loop, variant):
    if variant == "PROVISIONAL":
        value = loop["total_seconds"]
    elif loop["timing_state"] == "ABANDONED":
        value = ABANDON_PENALTY_SECONDS
    else:
        value = loop["adjusted_total_seconds"]
    return 0 if value is None else value


def open_remake_incidents_in_window(restaurant_id, window_start_at, window_end_at):
    total = 0
    for incident in db.accuracy_incidents.values():
        if incident["restaurant_id"] != restaurant_id:
            continue
        if incident["incident_state"] not in ("LOGGED", "REMADE"):
            continue
        loop = db.timer_loops.get(incident["timer_loop_id"])
        if loop is None or loop["arrive_at"] is None:
            continue
        if window_start_at <= loop["arrive_at"] < window_end_at:
            total += 1
    return total


def attainment_band(pct):
    if pct >= Decimal("110"):
        return "GOLD"
    if pct >= Decimal("100"):
        return "GREEN"
    if pct >= Decimal("90"):
        return "AMBER"
    return "RED"


def compute(restaurant, window_start_at, window_end_at, variant):
    """Every figure the report stores, computed once at creation."""
    window_seconds = seconds_between(window_end_at, window_start_at)
    loops = input_loops(restaurant["id"], window_start_at, window_end_at, variant)
    cars_served = len(loops)

    cars_per_hour = rhu(dec(cars_served) * 3600 / dec(window_seconds), 1)
    window_band = lookup_band(cars_per_hour)
    remakes = open_remake_incidents_in_window(restaurant["id"], window_start_at, window_end_at)

    result = {
        "metric_basis": "TOTAL" if variant == "PROVISIONAL" else "ADJUSTED_TOTAL",
        "cars_served": cars_served,
        "cars_per_hour": cars_per_hour,
        "window_tier": window_band["tier"],
        "avg_metric_seconds": None,
        "mean_pinned_target_seconds": None,
        "target_total_seconds_effective": None,
        "attainment_pct": None,
        "attainment_band": None,
        "open_remake_incident_count": remakes,
        "coaching_pool_points": 0,
        "_input_loop_ids": [loop["id"] for loop in loops],
    }

    if cars_served == 0:
        return result

    metric_total = sum(loop_metric(loop, variant) for loop in loops)
    avg_metric = rhu(dec(metric_total) / dec(cars_served), 1)
    pinned_total = sum(loop["target_total_seconds_pinned"] for loop in loops)
    mean_pinned = dec(pinned_total) / dec(cars_served)          # exact, unrounded

    relief = dec(window_band["target_relief_pct"])
    effective_target = rhu_int(mean_pinned * (ONE + relief))

    result["avg_metric_seconds"] = avg_metric
    result["mean_pinned_target_seconds"] = mean_pinned
    result["target_total_seconds_effective"] = effective_target

    if avg_metric > 0:
        pct = rhu(dec(100) * dec(effective_target) / avg_metric, 2)
        band = attainment_band(pct)
        result["attainment_pct"] = pct
        result["attainment_band"] = band
        band_points = BAND_POINTS[band]
    else:
        band_points = 0

    volume_points = min(VOLUME_POINTS_CAP, cars_served // VOLUME_POINTS_DIVISOR)
    result["coaching_pool_points"] = max(
        0, band_points + volume_points - REMAKE_POINT_PENALTY * remakes)

    return result
