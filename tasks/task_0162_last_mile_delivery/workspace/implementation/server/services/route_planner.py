"""Route-stop sequence, distance, and time-window assignment per PRD §3.7."""
import math
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal

from .. import store
from ..clock import iso8601_ms, parse_iso8601
from ..errors import raise_error
from .calculations import (
    AVG_SPEED_KMH,
    DISTANCE_BUCKET_KM,
    SERVICE_TIME_MIN,
    DEPART_HOUR_LOCAL,
    dec2,
    haversine_km,
    route_total_distance_km,
)


def _origin_coords(center: dict):
    lat = center.get("latitude")
    lon = center.get("longitude")
    if lat is None:
        lat = 0.0
    if lon is None:
        lon = 0.0
    return lat, lon


def stops_for_route_sorted(route_id: str):
    """Return all live route_stops belonging to the route, sorted by sequence."""
    items = [s for s in store.route_stops.values() if s["route_id"] == route_id]
    items.sort(key=lambda s: s["sequence"])
    return items


def recompute_route_derived(route: dict):
    """Recompute total_distance_km, stop_count, hazmat_present from current stops.
    Does NOT bump version/timestamps; the caller decides whether mutations occurred."""
    stops = stops_for_route_sorted(route["id"])
    route["stop_count"] = len(stops)
    hazmat = False
    for s in stops:
        p = store.parcels.get(s["parcel_id"])
        if p and p.get("hazmat_class", "NONE") != "NONE":
            hazmat = True
            break
    route["hazmat_present"] = hazmat
    center = store.transit_centers.get(route["center_id"])
    o_lat, o_lon = _origin_coords(center or {})
    def _dest_addr(parcel_id):
        parcel = store.parcels[parcel_id]
        return store.addresses[parcel["destination_address_id"]]
    total_km = route_total_distance_km(stops, _dest_addr, o_lat, o_lon)
    route["total_distance_km"] = total_km


def _truncate_to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def assign_planned_times(route: dict, stops_in_sequence):
    """Run the greedy time-assignment for all stops on the route in given sequence order.
    Mutates stops in-place (planned_arrival, planned_departure). Raises ERR_TIME_WINDOW_INFEASIBLE
    if any stop's arrival exceeds its parcel.time_window_end."""
    center = store.transit_centers.get(route["center_id"])
    o_lat, o_lon = _origin_coords(center or {})

    # Start cursor at route.planned_date 08:00 UTC. PRD says "local tz of origin center" but
    # without per-center tz info, treat planned_date as a UTC calendar date.
    planned_date_str = route["planned_date"]
    try:
        y, m, d = (int(x) for x in planned_date_str.split("-"))
        cursor = datetime(y, m, d, DEPART_HOUR_LOCAL, 0, 0, tzinfo=timezone.utc)
    except Exception:
        raise_error("ERR_TIME_WINDOW_INFEASIBLE", "Invalid planned_date")

    prev_lat, prev_lon = o_lat, o_lon
    for stop in stops_in_sequence:
        parcel = store.parcels[stop["parcel_id"]]
        addr = store.addresses[parcel["destination_address_id"]]
        leg_km = haversine_km(prev_lat, prev_lon, addr["latitude"], addr["longitude"])
        travel_min = math.ceil(float(leg_km) / float(AVG_SPEED_KMH) * 60)
        cursor = cursor + timedelta(minutes=travel_min)

        try:
            tw_start = parse_iso8601(parcel["time_window_start"])
            tw_end = parse_iso8601(parcel["time_window_end"])
        except Exception:
            raise_error("ERR_TIME_WINDOW_INFEASIBLE", "Invalid parcel time window")

        if cursor < tw_start:
            cursor = tw_start
        if cursor > tw_end:
            raise_error("ERR_TIME_WINDOW_INFEASIBLE")

        cursor = _truncate_to_minute(cursor)
        stop["planned_arrival"] = iso8601_ms(cursor)
        cursor = cursor + timedelta(minutes=SERVICE_TIME_MIN)
        stop["planned_departure"] = iso8601_ms(cursor)
        prev_lat = addr["latitude"]
        prev_lon = addr["longitude"]
