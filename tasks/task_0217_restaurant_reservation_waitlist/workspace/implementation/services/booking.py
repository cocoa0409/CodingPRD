"""Booking validation logic shared by create + reschedule (PRD §3.3, §3.4).

Checks, in priority order (the slice that applies to reservation writes):
party-size match -> service-period/slot -> table overlap -> area buyout ->
pacing -> OCC. Auth / existence / state / ownership / blocked / closed are
enforced by the caller before these run.
"""
from datetime import timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

import db
from errors import (
    err, ERR_PARTY_SIZE_MISMATCH, ERR_OUTSIDE_SERVICE_PERIOD,
    ERR_TABLE_DOUBLE_BOOKED, ERR_AREA_BOUGHT_OUT, ERR_PACING_EXCEEDED,
    ERR_STALE_TABLE_VERSION,
)
from services import calc

ACTIVE_RES_STATES = {"REQUESTED", "CONFIRMED", "SEATED"}


def _local_minutes(reservation_start, timezone_name):
    """Local wall-clock minute-of-day for an instant under the restaurant tz."""
    if ZoneInfo is not None:
        try:
            local = reservation_start.astimezone(ZoneInfo(timezone_name))
        except Exception:
            local = reservation_start
    else:  # pragma: no cover
        local = reservation_start
    return local, local.hour * 60 + local.minute


def _hhmm_to_minutes(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def check_party_size(table, party_size):
    if party_size < table["min_party_size"] or party_size > table["max_party_size"]:
        raise err(ERR_PARTY_SIZE_MISMATCH,
                  "party_size outside the table's [min, max] band")


def matching_service_period(restaurant, reservation_start):
    """Return the ServicePeriod whose window contains the local start AND whose
    slot grid the local start aligns to. Raises ERR_OUTSIDE_SERVICE_PERIOD if
    none. (PRD §2.5, §3.3)"""
    _, local_min = _local_minutes(reservation_start, restaurant["timezone"])
    for sp in db.service_periods.values():
        if sp["restaurant_id"] != restaurant["id"]:
            continue
        start_min = _hhmm_to_minutes(sp["start_local_time"])
        end_min = _hhmm_to_minutes(sp["end_local_time"])
        # half-open [start, end)
        if not (start_min <= local_min < end_min):
            continue
        interval = sp["slot_interval_minutes"]
        if (local_min - start_min) % interval == 0:
            return sp
    raise err(ERR_OUTSIDE_SERVICE_PERIOD,
              "reservation_start outside any service period or off the slot grid")


def _slot_grid_minute(local_min, sp):
    start_min = _hhmm_to_minutes(sp["start_local_time"])
    interval = sp["slot_interval_minutes"]
    k = (local_min - start_min) // interval
    return start_min + k * interval


def check_table_overlap(table_id, new_start, new_release, exclude_reservation_id=None):
    """No active reservation on the same table may have its half-open window
    [reservation_start, release_at) intersect the new window (PRD §3.3)."""
    for res in db.reservations.values():
        if res["id"] == exclude_reservation_id:
            continue
        if res["table_id"] != table_id:
            continue
        if res["status"] not in ACTIVE_RES_STATES:
            continue
        existing_start = res["reservation_start"]
        existing_release = res["release_at"]
        if existing_start is None or existing_release is None:
            continue
        # half-open intersection
        if new_start < existing_release and existing_start < new_release:
            raise err(ERR_TABLE_DOUBLE_BOOKED,
                      "window overlaps an active reservation on this table")


def check_area_buyout(table, new_start, new_release):
    """No CONFIRMED PrivateDiningEvent on the table's dining area may have its
    CLOSED window [event_start, event_end] intersect the reservation's window
    [reservation_start, release_at) (PRD §3.4)."""
    dining_area_id = table["dining_area_id"]
    for ev in db.private_dining_events.values():
        if ev["status"] != "CONFIRMED":
            continue
        if ev["dining_area_id"] != dining_area_id:
            continue
        # reservation window half-open [new_start, new_release); buyout window
        # closed [event_start, event_end]. Intersect iff start <= release-edge
        # and event_start < new_release (closed event end inclusive).
        if new_start <= ev["event_end"] and ev["event_start"] < new_release:
            raise err(ERR_AREA_BOUGHT_OUT,
                      "reservation window intersects a confirmed buyout")


def _slot_grid_instant(reservation_start, restaurant, sp):
    """Floor an instant onto its service-period slot grid, returning a tuple
    (local_date, slot_grid_minute) that uniquely identifies the slot. Two
    reservations share a slot iff this tuple is equal."""
    local, local_min = _local_minutes(reservation_start, restaurant["timezone"])
    grid_min = _slot_grid_minute(local_min, sp)
    return (local.date(), grid_min)


def check_pacing(restaurant, sp, reservation_start, party_size, exclude_reservation_id=None):
    """Projected slot covers must not exceed pacing cap (PRD §3.3).

    A "slot-grid time" is the reservation_start floored onto the service
    period's grid — a specific calendar instant (local date + grid minute),
    not a time-of-day shared across dates.
    """
    target_slot = _slot_grid_instant(reservation_start, restaurant, sp)
    current_load = 0
    for res in db.reservations.values():
        if res["id"] == exclude_reservation_id:
            continue
        if res["restaurant_id"] != restaurant["id"]:
            continue
        if res["status"] not in ACTIVE_RES_STATES:
            continue
        if res["reservation_start"] is None:
            continue
        _, res_local_min = _local_minutes(res["reservation_start"], restaurant["timezone"])
        res_sp = _period_for(restaurant, res_local_min)
        if res_sp is None or res_sp["id"] != sp["id"]:
            continue
        if _slot_grid_instant(res["reservation_start"], restaurant, res_sp) == target_slot:
            current_load += res["party_size"]
    projected = current_load + party_size
    if projected > sp["pacing_max_covers_per_slot"]:
        raise err(ERR_PACING_EXCEEDED, "projected slot covers exceed pacing cap")


def _period_for(restaurant, local_min):
    for sp in db.service_periods.values():
        if sp["restaurant_id"] != restaurant["id"]:
            continue
        start_min = _hhmm_to_minutes(sp["start_local_time"])
        end_min = _hhmm_to_minutes(sp["end_local_time"])
        if start_min <= local_min < end_min and (local_min - start_min) % sp["slot_interval_minutes"] == 0:
            return sp
    return None


def check_occ(table, expected_version):
    """expected_table_version must equal the live Table.version (PRD §2.9)."""
    if expected_version != table["version"]:
        raise err(ERR_STALE_TABLE_VERSION, "expected_table_version is stale")
