"""Resolve the geofence kind at a (lat, lng) location within a region.

PRD §3.4 / §3.5: end_fence_kind is one of ALLOWED_PARKING, RESTRICTED, NONE
(FORBIDDEN is blocked upstream). When more than one active fence contains
the point we apply a strict priority: FORBIDDEN > RESTRICTED > ALLOWED_PARKING.
"""
from __future__ import annotations

from typing import Optional

from db import geofences
from services.geometry import point_in_polygon


PRIORITY = {"FORBIDDEN": 3, "RESTRICTED": 2, "ALLOWED_PARKING": 1}


def fence_kind_at(region_id: str, lat: float, lng: float) -> str:
    """Return the highest-priority active fence kind at (lat,lng), else 'NONE'."""
    winner: Optional[str] = None
    winner_priority = -1
    for fence in geofences.values():
        if fence.get("region_id") != region_id:
            continue
        if not fence.get("active", True):
            continue
        if point_in_polygon(lat, lng, fence["polygon"]):
            kind = fence["kind"]
            if PRIORITY.get(kind, 0) > winner_priority:
                winner = kind
                winner_priority = PRIORITY[kind]
    return winner or "NONE"


def is_in_forbidden(region_id: str, lat: float, lng: float) -> bool:
    return fence_kind_at(region_id, lat, lng) == "FORBIDDEN"
