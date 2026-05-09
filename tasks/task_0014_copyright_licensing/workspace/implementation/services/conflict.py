"""Rights-conflict check (calc:rights_conflict_check)."""
from clock import parse_iso
from db import db
from errors import api_error


RELEVANT_STATUSES = {"ACCEPTED", "SIGNED", "EFFECTIVE"}


def _territory_overlap(a, b) -> bool:
    a_set = set(a or [])
    b_set = set(b or [])
    if "WORLD" in a_set or "WORLD" in b_set:
        return True
    return bool(a_set & b_set)


def _media_overlap(a, b) -> bool:
    return bool(set(a or []) & set(b or []))


def _term_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end) interval overlap. Adjacency does not overlap."""
    a_s = parse_iso(a_start)
    a_e = parse_iso(a_end)
    b_s = parse_iso(b_start)
    b_e = parse_iso(b_end)
    if not all([a_s, a_e, b_s, b_e]):
        return False
    # Truncate to second granularity.
    a_s = a_s.replace(microsecond=0)
    a_e = a_e.replace(microsecond=0)
    b_s = b_s.replace(microsecond=0)
    b_e = b_e.replace(microsecond=0)
    return (a_s < b_e) and (b_s < a_e)


def _conflict(other: dict, candidate: dict) -> bool:
    if other.get("id") == candidate.get("id"):
        return False
    if other.get("work_id") != candidate.get("work_id"):
        return False
    if other.get("status") not in RELEVANT_STATUSES:
        return False
    return (
        _territory_overlap(other.get("territory"), candidate.get("territory"))
        and _media_overlap(other.get("media_types"), candidate.get("media_types"))
        and _term_overlap(other.get("term_start"), other.get("term_end"),
                          candidate.get("term_start"), candidate.get("term_end"))
    )


def check_rights_conflict(candidate: dict):
    """Raise on exclusivity violation; return list of non-exclusive conflicts (audit-only).

    - If any incumbent EXCLUSIVE conflict → ERR_EXCLUSIVE_LICENSE_VIOLATION
    - If candidate is EXCLUSIVE and any conflict at all exists → ERR_EXCLUSIVE_LICENSE_VIOLATION
    - Else if both candidate and any conflicting incumbent are NON_EXCLUSIVE,
      return list of those incumbents (caller writes RIGHTS_CONFLICT_DETECTED audit).
    """
    conflicts = []
    for other in db.licenses.values():
        if _conflict(other, candidate):
            conflicts.append(other)

    if not conflicts:
        return []

    # Any exclusive incumbent blocking?
    if any(o.get("exclusivity") == "EXCLUSIVE" for o in conflicts):
        raise api_error("ERR_EXCLUSIVE_LICENSE_VIOLATION",
                        "An exclusive incumbent license overlaps the candidate slice")

    # Candidate exclusive but a conflict exists?
    if candidate.get("exclusivity") == "EXCLUSIVE":
        raise api_error("ERR_EXCLUSIVE_LICENSE_VIOLATION",
                        "Candidate is EXCLUSIVE and conflicts with another license")

    return conflicts
