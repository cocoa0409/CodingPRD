"""Great-circle distance helper for geofence checks."""
from __future__ import annotations

import math


EARTH_RADIUS_METERS = 6_371_000.0  # standard mean radius


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_METERS * c


def point_inside(neighborhood: dict, lat: float, lng: float) -> bool:
    dist = haversine_meters(
        float(neighborhood["center_lat"]),
        float(neighborhood["center_lng"]),
        float(lat),
        float(lng),
    )
    return dist <= float(neighborhood["radius_meters"])
