"""Cross-aggregate cascades (PRD 2.11)."""
from db import db, touch

from services import calc


def frames_of_program(program_id):
    return [f for f in db.sampling_frames.values() if f["program_id"] == program_id]


def apply_posture_cascade(program):
    """Link four of the completion posture cascade, and its inverse (PRD 3.3).

    A FROZEN posture suspends every SEALED frame; a posture back at OPEN or
    RESTRICTED re-seals every SUSPENDED frame of an ACTIVE or CLOSING program.
    """
    current = calc.posture(program)
    if current == "FROZEN":
        for frame in frames_of_program(program["id"]):
            if frame["status"] == "SEALED":
                frame["status"] = "SUSPENDED"
                touch(frame)
    elif program["status"] in ("ACTIVE", "CLOSING"):
        for frame in frames_of_program(program["id"]):
            if frame["status"] == "SUSPENDED":
                frame["status"] = "SEALED"
                touch(frame)


def expire_outstanding_assignments(card):
    """Expire every ASSIGNED or FAILED assignment on a card."""
    expired = []
    for assignment in calc.assignments_of_battlecard(card["id"]):
        if assignment["status"] in ("ASSIGNED", "FAILED"):
            assignment["status"] = "EXPIRED"
            touch(assignment)
            expired.append(assignment)
    return expired


def rescore_gaps_watch(watch, deal_id):
    """Register every NEW/TRIAGED gap whose linked deal set contains this deal."""
    for gap in db.product_gaps.values():
        if gap["status"] not in ("NEW", "TRIAGED"):
            continue
        linked_ids = {d["id"] for d in calc.gap_linked_deals(gap)}
        if deal_id in linked_ids:
            watch.watch(gap, calc.gap_metrics)


def watch_program_competitors(watch, program_id):
    for competitor in db.competitors.values():
        if competitor["program_id"] == program_id:
            watch.watch(competitor, calc.competitor_derived)
