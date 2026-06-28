"""Mastery / advancement engine (PRD §3.4, SCAFFOLD advancement calc).

Pinned evaluation order: count mastery, compare to threshold, then (and only
then) advance and recompute the count against the new level.
"""
from db import db
from services import calculations
from services.family_recompute import recompute_family


def _distinct_mastered_in_level(enrollment_id, level_id):
    sets = set()
    for w in db.worksheets.values():
        if (w["enrollment_id"] == enrollment_id
                and w["status"] == "MASTERED"
                and w["level_id"] == level_id):
            sets.add(w["set_number"])
    return len(sets)


def run_advancement(enr):
    """Called immediately after a Worksheet enters MASTERED. Mutates the
    enrollment (mastered_sets_in_level / current_level_id / status) with
    version bumps as needed."""
    current_level_id = enr["current_level_id"]
    if current_level_id is None:
        return

    # step 1: recompute mastery count for current level
    mastered = _distinct_mastered_in_level(enr["id"], current_level_id)

    current_level = db.levels.get(current_level_id)
    if current_level is None:
        if enr["mastered_sets_in_level"] != mastered:
            enr["mastered_sets_in_level"] = mastered
            db.touch(enr)
        return

    # step 3: only if threshold met, attempt advance
    if mastered >= current_level["worksheets_to_master"]:
        next_level = _next_level(current_level)
        if next_level is not None:
            enr["current_level_id"] = next_level["id"]
            # re-run step 1 against the new level
            enr["mastered_sets_in_level"] = _distinct_mastered_in_level(enr["id"], next_level["id"])
            db.touch(enr)
        else:
            # terminal level reached + target met -> COMPLETED
            enr["mastered_sets_in_level"] = mastered
            if enr["status"] == "ACTIVE":
                enr["status"] = "COMPLETED"
                db.touch(enr)
                recompute_family(_family_id(enr))
            else:
                db.touch(enr)
    else:
        if enr["mastered_sets_in_level"] != mastered:
            enr["mastered_sets_in_level"] = mastered
            db.touch(enr)


def _next_level(current_level):
    """Smallest-rank level in the same subject with rank strictly greater than
    current; tie-break created_at ASC (insertion order)."""
    candidates = [
        l for l in db.levels.values()
        if l["subject_id"] == current_level["subject_id"] and l["rank"] > current_level["rank"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda l: (l["rank"], l["_seq"]))
    return candidates[0]


def _family_id(enr):
    student = db.students.get(enr["student_id"])
    return student["family_id"] if student else None
