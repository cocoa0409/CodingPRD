"""Recruiting calendar resolution + contact permission matrix."""

from core.clock import parse_iso
from core.store import STORE


# Restrictiveness ranking (higher = more restrictive). DEAD wins all overlap ties.
PERIOD_RANK = {
    "QUIET": 1,
    "EVALUATION": 2,
    "CONTACT": 3,
    "DEAD": 4,
}

# Permission matrix: period_type -> {contact_type -> bool}.
PERMISSION_MATRIX = {
    "CONTACT": {
        "PHONE_CALL": True,
        "IN_PERSON_OFF_CAMPUS": True,
        "IN_PERSON_ON_CAMPUS": True,
        "TEXT_MESSAGE": True,
        "EVALUATION": True,
    },
    "QUIET": {
        "PHONE_CALL": True,
        "IN_PERSON_OFF_CAMPUS": False,
        "IN_PERSON_ON_CAMPUS": True,
        "TEXT_MESSAGE": True,
        "EVALUATION": False,
    },
    "DEAD": {
        "PHONE_CALL": False,
        "IN_PERSON_OFF_CAMPUS": False,
        "IN_PERSON_ON_CAMPUS": False,
        "TEXT_MESSAGE": False,
        "EVALUATION": False,
    },
    "EVALUATION": {
        "PHONE_CALL": True,
        "IN_PERSON_OFF_CAMPUS": False,
        "IN_PERSON_ON_CAMPUS": False,
        "TEXT_MESSAGE": True,
        "EVALUATION": True,
    },
}


def resolve_period(program_id: str, contact_at):
    """Resolve which RecruitingCalendar period_type covers contact_at.

    contact_at is a tz-aware UTC datetime. Returns the resolved period_type;
    if no window contains the moment, returns DEAD.
    """
    candidates = []
    for c in STORE.recruiting_calendars.values():
        if c.get("program_id") != program_id:
            continue
        start = parse_iso(c["start_date"])
        end = parse_iso(c["end_date"])
        if start <= contact_at < end:
            candidates.append(c["period_type"])
    if not candidates:
        return "DEAD"
    # Most restrictive wins.
    return max(candidates, key=lambda p: PERIOD_RANK[p])


def is_permitted(period_type: str, contact_type: str) -> bool:
    matrix = PERMISSION_MATRIX.get(period_type, {})
    return bool(matrix.get(contact_type, False))
