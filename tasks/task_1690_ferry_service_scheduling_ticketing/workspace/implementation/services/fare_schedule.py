"""Fare schedule lifecycle: lazy time-driven evaluation (PRD §2.4, §3.2).

APPROVED -> EFFECTIVE when current_utc covers the window; any prior EFFECTIVE
for the same route+season -> RETIRED. EFFECTIVE past effective_to -> RETIRED.
Evaluated on clock-set and lazily whenever a fare schedule is read/consulted.

Retirement flags bookings that pinned the retired schedule (status in
RESERVED/CONFIRMED/MODIFIED) for requote at next confirmation. We implement the
flag as a transient per-booking marker (`_requote`) — it is internal bookkeeping,
not a wire field — and confirmation re-quotes when the pinned schedule is no
longer EFFECTIVE (PRD §3.5), which subsumes the flag.
"""

from db import db, _parse_iso
from services.calculations import touch


def evaluate_fare_transitions():
    """Advance-based auto transitions against the logical clock."""
    now = db.current_utc

    # Pass 1: retire EFFECTIVE schedules whose window has passed.
    for f in list(db.fare_schedules.values()):
        if f["status"] != "EFFECTIVE":
            continue
        eff_to = _parse_iso(f["effective_to"])
        if now >= eff_to:
            _retire(f)

    # Pass 2: promote APPROVED schedules whose window now covers current_utc.
    # Process in created_at order so deterministic supersession when several
    # APPROVED windows for the same route+season all cover now.
    approved = [f for f in db.fare_schedules.values() if f["status"] == "APPROVED"]
    approved.sort(key=lambda f: (f["created_at"], f["id"]))
    for f in approved:
        eff_from = _parse_iso(f["effective_from"])
        eff_to = _parse_iso(f["effective_to"])
        if eff_from <= now < eff_to:
            # Supersede any EFFECTIVE schedule for same route+season.
            for other in list(db.fare_schedules.values()):
                if (other["id"] != f["id"] and other["status"] == "EFFECTIVE"
                        and other["route_id"] == f["route_id"]
                        and other["season"] == f["season"]):
                    _retire(other)
            f["status"] = "EFFECTIVE"
            touch(f)


def _retire(f):
    """EFFECTIVE -> RETIRED with booking requote flag (§3.2)."""
    f["status"] = "RETIRED"
    touch(f)
    for b in db.bookings.values():
        if (b.get("fare_schedule_id") == f["id"]
                and b["status"] in ("RESERVED", "CONFIRMED", "MODIFIED")):
            b["_requote"] = True


def find_effective_schedule(route_id, season, at_dt=None):
    """The EFFECTIVE schedule for route+season, lazily evaluating first.

    If `at_dt` is given (e.g. a sailing's departure_time), the schedule's
    window must also cover that instant.
    """
    evaluate_fare_transitions()
    candidates = [f for f in db.fare_schedules.values()
                  if f["route_id"] == route_id and f["season"] == season
                  and f["status"] == "EFFECTIVE"]
    if at_dt is not None:
        candidates = [f for f in candidates
                      if _parse_iso(f["effective_from"]) <= at_dt < _parse_iso(f["effective_to"])]
    if not candidates:
        return None
    candidates.sort(key=lambda f: (f["created_at"], f["id"]))
    return candidates[-1]


def windows_overlap(f1_from, f1_to, f2_from, f2_to):
    """Half-open [from, to) interval overlap."""
    return f1_from < f2_to and f2_from < f1_to


def has_live_overlap(route_id, season, eff_from, eff_to, exclude_id=None):
    """Any other FareSchedule for same route+season with status in
    {SUBMITTED, APPROVED, EFFECTIVE} and overlapping [from, to) window."""
    evaluate_fare_transitions()
    for f in db.fare_schedules.values():
        if exclude_id is not None and f["id"] == exclude_id:
            continue
        if f["route_id"] != route_id or f["season"] != season:
            continue
        if f["status"] not in ("SUBMITTED", "APPROVED", "EFFECTIVE"):
            continue
        if windows_overlap(eff_from, eff_to,
                           _parse_iso(f["effective_from"]),
                           _parse_iso(f["effective_to"])):
            return True
    return False
