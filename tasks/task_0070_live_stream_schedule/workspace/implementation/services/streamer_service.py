"""Streamer mutations — keep tier and suspension reconciliation consistent."""

from __future__ import annotations

import db
import clock
from services.calculations import calc_performance_tier


def recompute_tier(streamer: dict) -> None:
    """In-place recompute of the streamer's tier from gmv + violation_score."""
    streamer["tier"] = calc_performance_tier(
        lifetime_gmv_cents=streamer.get("lifetime_gmv_cents", 0),
        violation_score=streamer.get("violation_score", 0),
        status=streamer.get("status", "ACTIVE"),
    )


def reconcile_suspension(streamer: dict) -> None:
    """If suspension_until <= now, clear the suspension. Does not modify
    BLACKLISTED streamers (they have null suspension_until).
    """
    if streamer.get("status") != "SUSPENDED":
        return
    until = streamer.get("suspension_until")
    if not until:
        return
    if clock.parse_iso(until) <= clock.now():
        streamer["status"] = "ACTIVE"
        streamer["suspension_until"] = None


def apply_cascade(streamer_id: str) -> dict | None:
    """Apply tier recompute + suspension reconciliation in a single update,
    bumping version and timestamp once. Returns the updated entity (deepcopy)
    or None if the streamer does not exist.
    """
    if db.raw_get("streamers", streamer_id) is None:
        return None

    def mutate(s):
        reconcile_suspension(s)
        recompute_tier(s)
    return db.update_entity("streamers", streamer_id, mutate)
