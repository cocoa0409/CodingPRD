"""Lease overlap and renovation conflict helpers."""
from datetime import timedelta

from clock import parse_iso
import db
from services.calendar_utils import half_open_overlap, closed_interval_overlap_half_open


_NON_TERMINAL_STATES = {"SIGNED", "ACTIVE", "AMENDMENT_PENDING", "TERMINATING"}


def overlapping_lease_exists(unit_id: str, start_dt, end_dt, *, exclude_lease_id=None) -> bool:
    """Returns True if any non-terminated lease on this unit overlaps [start_dt, end_dt)."""
    for le in db.leases.values():
        if le.get("unit_id") != unit_id:
            continue
        if exclude_lease_id is not None and le["id"] == exclude_lease_id:
            continue
        if le.get("status") not in _NON_TERMINAL_STATES:
            continue
        ls = parse_iso(le["start_date"])
        led = parse_iso(le["end_date"])
        if half_open_overlap(ls, led, start_dt, end_dt):
            return True
    return False


def renovation_conflicts(unit: dict, start_dt, end_dt) -> bool:
    """Returns True if the unit's current renovation interval (extended by 1 day buffer at end)
    overlaps [start_dt, end_dt)."""
    rs = unit.get("renovation_start_date")
    re = unit.get("renovation_end_date")
    if not rs or not re:
        return False
    rs_dt = parse_iso(rs)
    re_dt = parse_iso(re)
    # Closed interval [renovation_start_date, renovation_end_date + 1 day]
    extended_end = re_dt + timedelta(days=1)
    return closed_interval_overlap_half_open(rs_dt, extended_end, start_dt, end_dt)


def lease_overlaps_renovation_for_unit(unit_id: str, ren_start, ren_end_inclusive_plus_1) -> bool:
    """Returns True if any non-terminated lease on this unit has [start,end) intersecting
    the closed-with-buffer interval [ren_start, ren_end + 1 day]."""
    for le in db.leases.values():
        if le.get("unit_id") != unit_id:
            continue
        if le.get("status") not in _NON_TERMINAL_STATES:
            continue
        ls = parse_iso(le["start_date"])
        led = parse_iso(le["end_date"])
        if closed_interval_overlap_half_open(ren_start, ren_end_inclusive_plus_1, ls, led):
            return True
    return False
