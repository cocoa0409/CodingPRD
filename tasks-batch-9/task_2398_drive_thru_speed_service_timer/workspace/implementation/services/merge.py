"""merge_award_selection (waterfall allocation over the eligible loops)."""

from db import base_row, db, touch
from errors import fail
from services.rollup import lookup_band


def _slots_of(restaurant_id):
    return [row for row in db.merge_slots.values() if row["restaurant_id"] == restaurant_id]


def last_slot(restaurant_id):
    slots = _slots_of(restaurant_id)
    if not slots:
        return None
    return max(slots, key=lambda row: row["sequence_index"])


def occupied_count(restaurant_id):
    return len([row for row in _slots_of(restaurant_id)
                if row["slot_state"] in ("RESERVED", "COMMITTED")])


def eligible_loops(restaurant):
    out = []
    for loop in db.timer_loops.values():
        if loop["restaurant_id"] != restaurant["id"]:
            continue
        if loop["timing_state"] != "ORDERED":
            continue
        if loop["accuracy_state"] not in ("PENDING", "VERIFIED"):
            continue
        held = [row for row in db.merge_slots.values()
                if row["timer_loop_id"] == loop["id"]
                and row["slot_state"] in ("RESERVED", "COMMITTED")]
        if held:
            continue
        live_pf = [row for row in db.pull_forward_orders.values()
                   if row["timer_loop_id"] == loop["id"]
                   and row["pf_state"] in ("ISSUED", "PARKED")]
        if live_pf:
            continue
        out.append(loop)
    return out


def _rank_key(loop, bias, preferred_lane):
    if bias == "ALTERNATE":
        group = 0 if (preferred_lane is None or loop["lane"] == preferred_lane) else 1
        return (group, loop["order_complete_at"])
    if bias == "ACCURACY_FIRST":
        group = 0 if loop["accuracy_state"] == "VERIFIED" else 1
        return (group, loop["order_complete_at"])
    return (loop["order_complete_at"],)


def award(restaurant):
    """Runs after the posture gates; raises the ladder's 30 / 32 errors itself."""
    band = lookup_band(restaurant["cars_per_hour_effective"])
    candidates = eligible_loops(restaurant)
    if not candidates:
        fail("ERR_NO_MERGE_CANDIDATE", "no loop of this store is eligible for a merge slot")
    if restaurant["merge_slots_capacity"] - occupied_count(restaurant["id"]) < 1:
        fail("ERR_MERGE_CAPACITY_EXHAUSTED", "every post-merge position is already held")

    bias = band["merge_award_bias"]
    previous = last_slot(restaurant["id"])

    preferred_lane = None
    if bias == "ALTERNATE" and previous is not None:
        if previous["source_lane"] == "LANE_A":
            preferred_lane = "LANE_B"
        elif previous["source_lane"] == "LANE_B":
            preferred_lane = "LANE_A"

    keyed = [(_rank_key(loop, bias, preferred_lane), loop) for loop in candidates]
    best_key = min(key for key, _loop in keyed)
    tied = [loop for key, loop in keyed if key == best_key]

    if len(tied) > 1:
        winner = min(tied, key=lambda loop: loop["car_sequence"])
        award_reason = "CAR_SEQUENCE_TIE_BREAK"
    else:
        winner = tied[0]
        award_reason = bias

    sequence_index = 1
    if previous is not None:
        sequence_index = previous["sequence_index"] + 1

    slot = base_row()
    slot.update({
        "restaurant_id": restaurant["id"],
        "timer_loop_id": winner["id"],
        "sequence_index": sequence_index,
        "source_lane": winner["lane"],
        "awarded_at": db.clock,
        "award_reason": award_reason,
        "slot_state": "RESERVED",
    })
    db.merge_slots[slot["id"]] = slot

    winner["served_after_loop_id"] = previous["timer_loop_id"] if previous is not None else None
    touch(winner)

    return slot
