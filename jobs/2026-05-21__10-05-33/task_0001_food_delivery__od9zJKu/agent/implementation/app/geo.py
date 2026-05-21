"""Geographic helpers."""
from __future__ import annotations

import math


EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km between two (lat,lng) points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def round_km_1dp(km: float) -> float:
    """Round half-up to 1 decimal place."""
    # Python's round is banker's; use a shift to round half-up.
    return math.floor(km * 10 + 0.5) / 10
