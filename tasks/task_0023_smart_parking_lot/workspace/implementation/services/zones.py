"""Zone counter recomputation helpers."""
import db


def recompute_zone_counts(zone_id: str) -> None:
    """Recompute denormalized total_spaces and free_spaces for a zone."""
    zone = db.zones.get(zone_id)
    if zone is None:
        return
    total = 0
    free = 0
    for s in db.spaces.values():
        if s.get("zone_id") != zone_id:
            continue
        total += 1
        if s.get("occupancy_status") == "FREE" and s.get("reservation_lock") == "UNRESERVED":
            free += 1
    if zone.get("total_spaces") != total or zone.get("free_spaces") != free:
        zone["total_spaces"] = total
        zone["free_spaces"] = free
        db.stamp_update(zone)


def recompute_all_zones() -> int:
    """Sweep helper — returns count of zones touched."""
    n = 0
    for zid in list(db.zones.keys()):
        recompute_zone_counts(zid)
        n += 1
    return n
