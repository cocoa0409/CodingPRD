"""Cross-entity cascades and ledger-counter sync (PRD 2.8, section 3).

Building version convention: an endpoint that mutates building ledger
counters bumps Building.version once per API call (scaffold endpoint side
effects state "Building.version += 1" once per operation).
"""
from datetime import timedelta

from db import store
from store_ops import new_id, new_common_fields, touch
from timeutil import as_instant


def building_of_room(room):
    return store.buildings[room["building_id"]]


def room_has_active_assignment(room_id):
    return any(
        a["room_id"] == room_id and a["status"] in ("RESERVED", "CHECKED_IN")
        for a in store.assignments.values()
    )


def room_has_checked_in(room_id):
    return any(
        a["room_id"] == room_id and a["status"] == "CHECKED_IN"
        for a in store.assignments.values()
    )


def adjust_bed_counters(building, delta):
    building["reserved_bed_count"] += delta
    building["available_bed_count"] = building["released_bed_count"] - building["reserved_bed_count"]


def release_room_if_emptied(room):
    """Conditional cascade: RESERVED -> RELEASED when no active assignment
    (RESERVED or CHECKED_IN) remains on the room."""
    if room["status"] == "RESERVED" and not room_has_active_assignment(room["id"]):
        room["status"] = "RELEASED"
        touch(room)


def cancel_reserved_assignment(asn):
    """RESERVED -> CANCELLED with ledger sync and conditional room cascade.
    Building version is bumped once by the calling endpoint."""
    asn["status"] = "CANCELLED"
    touch(asn)
    room = store.rooms[asn["room_id"]]
    building = building_of_room(room)
    adjust_bed_counters(building, -1)
    release_room_if_emptied(room)


def no_show_assignment(asn):
    """RESERVED -> NO_SHOW with ledger sync and conditional room cascade."""
    asn["status"] = "NO_SHOW"
    touch(asn)
    room = store.rooms[asn["room_id"]]
    building = building_of_room(room)
    adjust_bed_counters(building, -1)
    release_room_if_emptied(room)


def check_in_assignment(asn):
    """RESERVED -> CHECKED_IN; bubbles room (first occupant) and group
    (first check-in of the group)."""
    asn["status"] = "CHECKED_IN"
    asn["actual_checkin_at"] = store.clock
    touch(asn)
    room = store.rooms[asn["room_id"]]
    if room["status"] == "RESERVED":
        room["status"] = "OCCUPIED"
        touch(room)
    group = store.groups[asn["group_id"]]
    if group["status"] == "CONFIRMED":
        group["status"] = "IN_HOUSE"
        touch(group)


def spawn_turn_task(room, departing_assignment):
    """TurnTask created when a room empties (PRD 3.6): window starts at the
    triggering checkout instant; window end is the earliest future RESERVED
    check-in on the room, else window_start + 7 days; linen tier is the
    incoming group's when a next reservation exists, else the departing
    group's."""
    window_start = departing_assignment["actual_checkout_at"]
    future = [
        a for a in store.assignments.values()
        if a["room_id"] == room["id"]
        and a["status"] == "RESERVED"
        and as_instant(a["checkin_at"]) > window_start
    ]
    if future:
        nxt = min(future, key=lambda a: as_instant(a["checkin_at"]))
        window_end = as_instant(nxt["checkin_at"])
        tier = store.groups[nxt["group_id"]]["linen_tier"]
    else:
        window_end = window_start + timedelta(days=7)
        tier = store.groups[departing_assignment["group_id"]]["linen_tier"]
    task = {
        "id": new_id(),
        "_seq": next(store.seq),
        "room_id": room["id"],
        "window_start": window_start,
        "window_end": window_end,
        "linen_tier": tier,
        "status": "SCHEDULED",
        "rework_count": 0,
        "inspector_note": None,
    }
    task.update(new_common_fields())
    store.turn_tasks[task["id"]] = task
    room["active_turn_task_id"] = task["id"]
    building = building_of_room(room)
    building["scheduled_turn_count"] += 1


def check_out_assignment(asn):
    """CHECKED_IN -> CHECKED_OUT; ledger sync; last checkout cascades the
    room to NEEDS_TURN and spawns its turn task."""
    asn["status"] = "CHECKED_OUT"
    asn["actual_checkout_at"] = store.clock
    touch(asn)
    room = store.rooms[asn["room_id"]]
    building = building_of_room(room)
    adjust_bed_counters(building, -1)
    if not room_has_checked_in(room["id"]):
        room["status"] = "NEEDS_TURN"
        spawn_turn_task(room, asn)
        touch(room)
    touch(building)
