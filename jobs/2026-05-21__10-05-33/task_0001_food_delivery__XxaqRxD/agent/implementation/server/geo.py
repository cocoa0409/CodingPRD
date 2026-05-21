"""Geographic helpers."""
from __future__ import annotations

import math


_R_KM = 6371.0088  # mean Earth radius


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _R_KM * c


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    return haversine_km(lat1, lng1, lat2, lng2) * 1000.0


def round_distance_km(km: float) -> float:
    """Round to one decimal place (half-up). The PRD doesn't enforce a rounding
    mode for the displayed distance; Python's built-in `round` uses banker's
    rounding, so we implement explicit half-up here."""
    from decimal import Decimal, ROUND_HALF_UP

    return float(Decimal(str(km)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
