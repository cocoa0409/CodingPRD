"""Geographic helpers."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def round_distance_km(d: float) -> float:
    """Round to 1 decimal place (half-up)."""
    return float(round_half_up(d * 10) / 10)


def round_half_up(value: float) -> int:
    """Round half-up to nearest integer (positive values)."""
    return int(math.floor(value + 0.5)) if value >= 0 else -int(math.floor(-value + 0.5))
