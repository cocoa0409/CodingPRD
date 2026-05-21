"""Cascading-mutation helpers (flight cancellation, etc.)."""

from __future__ import annotations

from ..store import store
from .common import bump_version


def cascade_flight_cancel(flight_id: str) -> None:
    """When a flight is cancelled, cascade to segments and upgrades.

    Every BOOKED FlightSegment for this flight goes to CANCELLED, and every
    WAITLISTED UpgradeRequest for those segments goes to CANCELLED with held_points
    cleared.
    """
    for s in store.segments.values():
        if s["flight_id"] != flight_id:
            continue
        if s["status"] == "BOOKED":
            s["status"] = "CANCELLED"
            bump_version(s)
            # cascade child upgrade requests on this segment
            for u in store.upgrade_requests.values():
                if u["flight_segment_id"] == s["id"] and u["status"] == "WAITLISTED":
                    u["status"] = "CANCELLED"
                    u["held_points"] = 0
                    bump_version(u)
