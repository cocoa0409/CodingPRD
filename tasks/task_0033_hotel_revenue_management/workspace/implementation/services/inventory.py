"""Inventory & overbooking checks for reservation confirm/modify."""
from datetime import date

from db import (
    rooms as rooms_table,
    maintenance_blocks,
    reservations as reservations_table,
    channel_rate_plan_mappings,
    overbooking_policies,
)
from clock import parse_date, daterange


def physical_capacity_for_date(room_type_id: str, d: date) -> int:
    """Count of ACTIVE rooms of this room_type minus those blocked by SCHEDULED/ACTIVE maintenance covering date d."""
    active_rooms = [
        r for r in rooms_table.values()
        if r.get("room_type_id") == room_type_id and r.get("lifecycle_status") == "ACTIVE"
    ]
    physical = len(active_rooms)
    blocked = 0
    for r in active_rooms:
        for b in maintenance_blocks.values():
            if (b.get("room_id") == r["id"]
                    and b.get("status") in ("SCHEDULED", "ACTIVE")):
                bs = parse_date(b["start_date"])
                be = parse_date(b["end_date"])
                if bs <= d < be:
                    blocked += 1
                    break
    return physical - blocked


def find_mapping(channel_id: str, rate_plan_id: str):
    for m in channel_rate_plan_mappings.values():
        if m.get("channel_id") == channel_id and m.get("rate_plan_id") == rate_plan_id:
            return m
    return None


def check_channel_inventory_remaining(reservation: dict, *, exclude_reservation_id: str = None) -> bool:
    """Return True if for every night the per-channel allotted share has at least one slot remaining."""
    mapping = find_mapping(reservation["channel_id"], reservation["rate_plan_id"])
    if mapping is None or not mapping.get("enabled", True):
        # caller upstream is expected to surface ERR_RATE_PLAN_NOT_DISTRIBUTED earlier;
        # if we get here, conservatively reject.
        return False
    share_bp = mapping["inventory_share_basis_points"]

    ci = parse_date(reservation["check_in_date"])
    co = parse_date(reservation["check_out_date"])
    for d in daterange(ci, co):
        capacity = physical_capacity_for_date(reservation["room_type_id"], d)
        channel_share = (capacity * share_bp) // 10000  # floor
        used = 0
        for r in reservations_table.values():
            if exclude_reservation_id and r.get("id") == exclude_reservation_id:
                continue
            if (r.get("channel_id") == reservation["channel_id"]
                    and r.get("rate_plan_id") == reservation["rate_plan_id"]
                    and r.get("booking_status") in ("CONFIRMED", "CHECKED_IN")):
                rci = parse_date(r["check_in_date"])
                rco = parse_date(r["check_out_date"])
                if rci <= d < rco:
                    used += 1
        remaining = channel_share - used
        if remaining < 1:
            return False
    return True


def check_overbooking_limit(reservation: dict, *, exclude_reservation_id: str = None) -> tuple:
    """Return (ok, hit_overbooking) for the reservation across [check_in, check_out).

    hit_overbooking is True iff the candidate's confirmation pushes any night's cumulative count
    strictly past physical_capacity (i.e., overbooking ratio is exercised) — we use this to know
    whether to emit the OVERBOOKING_ACCEPTED audit event.
    """
    ci = parse_date(reservation["check_in_date"])
    co = parse_date(reservation["check_out_date"])
    hit_overbooking = False
    for d in daterange(ci, co):
        capacity = physical_capacity_for_date(reservation["room_type_id"], d)
        # find ACTIVE policy
        ratio_bp = 0
        iso_d = d.isoformat()
        for p in overbooking_policies.values():
            if (p.get("room_type_id") == reservation["room_type_id"]
                    and p.get("stay_date") == iso_d
                    and p.get("status") == "ACTIVE"):
                ratio_bp = p["overbook_ratio_basis_points"]
                break
        ceiling = capacity + (capacity * ratio_bp) // 10000

        cumulative = 0
        for r in reservations_table.values():
            if exclude_reservation_id and r.get("id") == exclude_reservation_id:
                continue
            if (r.get("room_type_id") == reservation["room_type_id"]
                    and r.get("booking_status") in ("CONFIRMED", "CHECKED_IN")):
                rci = parse_date(r["check_in_date"])
                rco = parse_date(r["check_out_date"])
                if rci <= d < rco:
                    cumulative += 1
        cumulative += 1  # +1 for the candidate
        if cumulative > ceiling:
            return (False, hit_overbooking)
        if cumulative > capacity:
            hit_overbooking = True
    return (True, hit_overbooking)


def physical_room_available_for_check_in(room_type_id: str, ci: date, co: date) -> int:
    """Count of physical rooms simultaneously VACANT_CLEAN, IN_SERVICE, and free of any
    overlapping MaintenanceBlock for the entire stay window. Used in walk-out precondition."""
    count = 0
    for r in rooms_table.values():
        if r.get("room_type_id") != room_type_id:
            continue
        if r.get("lifecycle_status") != "ACTIVE":
            continue
        if r.get("housekeeping_status") != "VACANT_CLEAN":
            continue
        if r.get("operational_status") != "IN_SERVICE":
            continue
        # check maintenance overlap any night in [ci, co)
        overlap = False
        for b in maintenance_blocks.values():
            if b.get("room_id") != r["id"]:
                continue
            if b.get("status") not in ("SCHEDULED", "ACTIVE"):
                continue
            bs = parse_date(b["start_date"])
            be = parse_date(b["end_date"])
            # half-open windows overlap iff bs < co AND be > ci
            if bs < co and be > ci:
                overlap = True
                break
        if not overlap:
            count += 1
    return count


def date_overlaps_any_block(room_id: str, ci: date, co: date) -> bool:
    """True if any SCHEDULED/ACTIVE maintenance block on this room overlaps [ci, co)."""
    for b in maintenance_blocks.values():
        if b.get("room_id") != room_id:
            continue
        if b.get("status") not in ("SCHEDULED", "ACTIVE"):
            continue
        bs = parse_date(b["start_date"])
        be = parse_date(b["end_date"])
        if bs < co and be > ci:
            return True
    return False
