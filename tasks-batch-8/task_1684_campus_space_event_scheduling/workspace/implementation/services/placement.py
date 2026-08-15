"""The scheduling placement waterfall (PRD 3.3, SCAFFOLD scheduling_placement).

PASS 1 (score): compute priority_score for every UNPLACED block of the term
from request data only.
PASS 2 (order): sort by priority_score DESC, enrollment DESC, created_at ASC.
PASS 3 (assign): per block, candidates are ACTIVE rooms with capacity >=
enrollment and a features superset.  First try free candidates (no PLACED-block
instance overlap, no event occupancy conflict at all); else bumpable candidates
(no PLACED-block overlap; every conflicting event bumpable), bumping them with
the full cascade; else the block remains UNPLACED.  Best fit = min
(capacity - enrollment), ties broken by the earliest-created room.
"""

import db
from constants import ENROLLMENT_WEIGHT, FEATURE_WEIGHTS, LARGE_CLASS_BONUS, LARGE_CLASS_THRESHOLD
from services.cascade import bump_event
from services.intervals import (
    block_instances,
    is_bumpable,
    placed_block_overlap,
    placement_conflicting_events,
)


def priority_score(block):
    """enrollment*10 + sum(feature weights) + 100 if enrollment >= 100.
    Computed from the block's request data only, never from any candidate
    room."""
    score = block.get("enrollment", 0) * ENROLLMENT_WEIGHT
    score += sum(FEATURE_WEIGHTS[f] for f in block.get("required_features", []))
    if block.get("enrollment", 0) >= LARGE_CLASS_THRESHOLD:
        score += LARGE_CLASS_BONUS
    return score


def _best_fit(candidates, block):
    """min(capacity - enrollment); tie-break earliest Room.created_at."""
    enrollment = block.get("enrollment", 0)
    return min(
        candidates,
        key=lambda room: (room.get("capacity", 0) - enrollment, room["_created_dt"], room["_seq"]),
    )


def _is_candidate(room, block):
    if room.get("status") != "ACTIVE":
        return False
    if room.get("capacity", 0) < block.get("enrollment", 0):
        return False
    if not set(block.get("required_features", [])) <= set(room.get("features", [])):
        return False
    return True


def run_placement(run, term, now):
    # PASS 1 - score every UNPLACED block before any assignment is considered.
    blocks = [
        b
        for b in db.academic_blocks.values()
        if b.get("term_id") == term["id"] and b.get("status") == "UNPLACED"
    ]
    for block in blocks:
        block["priority_score"] = priority_score(block)

    # PASS 2 - deterministic processing order.
    blocks.sort(
        key=lambda b: (
            -b["priority_score"],
            -b.get("enrollment", 0),
            b["_created_dt"],
            b["_seq"],
        )
    )

    placed_count = 0
    bumped_event_ids = []
    unplaced_block_ids = []

    # PASS 3 - assign each block in order.
    for block in blocks:
        instances = block_instances(block)
        candidates = [r for r in db.rooms.values() if _is_candidate(r, block)]

        free = []
        bumpable = []
        for room in candidates:
            if placed_block_overlap(room, instances):
                continue
            conflicts = placement_conflicting_events(room, instances)
            if not conflicts:
                free.append(room)
            elif all(is_bumpable(event, now) for event in conflicts):
                bumpable.append((room, conflicts))

        chosen_room = None
        chosen_conflicts = []
        if free:
            chosen_room = _best_fit(free, block)
        elif bumpable:
            chosen_room = _best_fit([room for room, _ in bumpable], block)
            chosen_conflicts = next(c for r, c in bumpable if r["id"] == chosen_room["id"])

        if chosen_room is not None:
            for event in chosen_conflicts:
                bump_event(event)
                bumped_event_ids.append(event["id"])
            block["status"] = "PLACED"
            block["assigned_room_id"] = chosen_room["id"]
            block["scheduling_run_id"] = run["id"]
            db.touch(block)
            placed_count += 1
        else:
            unplaced_block_ids.append(block["id"])

    run["placed_count"] = placed_count
    run["bumped_event_ids"] = bumped_event_ids
    run["unplaced_block_ids"] = unplaced_block_ids
