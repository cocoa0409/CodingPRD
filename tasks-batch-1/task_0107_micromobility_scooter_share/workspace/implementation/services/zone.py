"""Zone resolution and geofence behaviour (PRD §2.5).

A vehicle carries a single `current_zone_id` and a trip end supplies a single
`end_zone_id`; each names exactly one Zone. The "resolved zone" of a vehicle or
of an end-zone reference is therefore the Zone identified by that id. The
priority/created_at overlap-resolution rule (PRD §2.5) governs which zone wins
when a geographic point falls inside several overlapping zones; since this API
records a single resolved zone id per location, resolution is a direct lookup of
that id. The helper below still exposes priority-based resolution for any caller
that needs to resolve a set of candidate zones deterministically.
"""
from db import db

RIDE_OK = "RIDE_OK"
SLOW = "SLOW"
NO_RIDE = "NO_RIDE"
NO_PARK = "NO_PARK"
ZONE_TYPES = {RIDE_OK, SLOW, NO_RIDE, NO_PARK}


def get_zone(zone_id):
    """Return the Zone record for zone_id, or None."""
    return db.zones.get(zone_id)


def resolve_zone(zone_id):
    """Resolve a zone reference to its effective Zone record (PRD §2.5).

    With a single named zone id the resolution is a direct lookup.
    """
    return db.zones.get(zone_id)


def resolve_candidates(zone_ids):
    """Deterministically resolve a set of overlapping candidate zones (PRD §2.5).

    The effective zone is the one whose `priority` integer is smallest; ties on
    `priority` are broken by the earliest `created_at` (insertion sequence).
    """
    zones = [db.zones[z] for z in zone_ids if z in db.zones]
    if not zones:
        return None
    return min(zones, key=lambda z: (z["priority"], z.get("_seq", 0)))


def is_slow(zone_id):
    z = resolve_zone(zone_id)
    return z is not None and z["zone_type"] == SLOW


def is_no_ride(zone_id):
    z = resolve_zone(zone_id)
    return z is not None and z["zone_type"] == NO_RIDE


def is_no_park(zone_id):
    z = resolve_zone(zone_id)
    return z is not None and z["zone_type"] == NO_PARK
