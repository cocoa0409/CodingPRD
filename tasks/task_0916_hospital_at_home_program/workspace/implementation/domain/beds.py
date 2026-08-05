"""BedReservation lifecycle and the lazy hold expiry of PRD 3.8."""

import clock
import derived
import store
from store import DB


def expire_reservation_if_due(reservation):
    """HELD -> EXPIRED once the clock is STRICTLY past hold_expires_at."""
    if reservation["status"] != "HELD":
        return False
    expires_at = clock.parse_iso(reservation["hold_expires_at"])
    if clock.now_dt() > expires_at:
        reservation["status"] = "EXPIRED"
        store.touch(reservation)
        return True
    return False


def sweep_unit(unit_id):
    """Lazily expire every stale hold of one unit."""
    for reservation in derived.unit_reservations(unit_id):
        expire_reservation_if_due(reservation)


def earliest_held_reservation(episode_id):
    """held_at ascending, created_at ascending breaking ties."""
    candidates = [
        r for r in DB.reservations.values()
        if r["episode_id"] == episode_id and r["status"] == "HELD"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (clock.parse_iso(r["held_at"]), r["_created_dt"], r["_seq"]))
    return candidates[0]


def occupy(reservation):
    reservation["status"] = "OCCUPIED"
    reservation["occupied_at"] = clock.now_raw()
    store.touch(reservation)


def release_for_episode(episode_id):
    """Readmission drives every HELD or OCCUPIED reservation to RELEASED."""
    for reservation in derived.episode_reservations(episode_id):
        if reservation["status"] in ("HELD", "OCCUPIED"):
            reservation["status"] = "RELEASED"
            store.touch(reservation)
