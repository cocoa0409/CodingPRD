"""Timeline overlap rules.

Per-vendor: among slots sharing the same vendor_id, no pair may overlap.
Project parallel-CEREMONY cap: among slots filtered to kind == CEREMONY,
the count of slots active at any single instant must not exceed
MAX_PARALLEL_CEREMONY_SLOTS = 2.

Overlap definition (calculation timeline_overlap_check):
  Two slots A and B overlap iff
    max(A.start_at - A.setup_buffer_seconds, B.start_at - B.setup_buffer_seconds)
      < min(A.end_at, B.end_at)
  Adjacency without overlap is allowed (half-open intervals).
"""

import db
from errors import (
    raise_error,
    ERR_TIMELINE_VENDOR_OVERLAP,
    ERR_TIMELINE_PARALLEL_CAP_EXCEEDED,
)


MAX_PARALLEL_CEREMONY_SLOTS = 2


def _eff_start(slot):
    return int(slot["start_at"]) - int(slot.get("setup_buffer_seconds") or 0)


def _eff_end(slot):
    return int(slot["end_at"])


def _overlap(a, b) -> bool:
    return max(_eff_start(a), _eff_start(b)) < min(_eff_end(a), _eff_end(b))


def check_overlap_rules(project_id: str, candidate: dict, exclude_id: str = None):
    """Validates the candidate slot against existing slots on the project."""
    others = [
        s for s in db.timeline_slots.values()
        if s["project_id"] == project_id and s["id"] != exclude_id
    ]

    # Per-vendor rule (only if candidate has a vendor_id)
    if candidate.get("vendor_id"):
        for other in others:
            if other.get("vendor_id") != candidate["vendor_id"]:
                continue
            if _overlap(candidate, other):
                raise_error(ERR_TIMELINE_VENDOR_OVERLAP,
                            "Per-vendor timeline overlap")

    # Parallel CEREMONY cap rule
    if candidate.get("kind", "CEREMONY") == "CEREMONY":
        ceremony_pool = [s for s in others if s.get("kind", "CEREMONY") == "CEREMONY"]
        # Endpoints are integers; check at every event boundary involving the candidate.
        events = set()
        events.add(_eff_start(candidate))
        events.add(_eff_end(candidate) - 1)
        for s in ceremony_pool:
            events.add(_eff_start(s))
            events.add(_eff_end(s) - 1)
        for t in events:
            count = 0
            if _eff_start(candidate) <= t < _eff_end(candidate):
                count += 1
            for s in ceremony_pool:
                if _eff_start(s) <= t < _eff_end(s):
                    count += 1
            if count > MAX_PARALLEL_CEREMONY_SLOTS:
                raise_error(ERR_TIMELINE_PARALLEL_CAP_EXCEEDED,
                            "Too many parallel CEREMONY slots")
