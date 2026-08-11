"""Entity serializers. Hidden bookkeeping fields (prefixed _) are stripped."""

from db import db

_HIDDEN = ("_insert_seq", "_sched_seq")


def _clean(rec):
    return {k: v for k, v in rec.items() if k not in _HIDDEN}


def service_line_json(s):
    return _clean(s)


def surgeon_json(s):
    return _clean(s)


def room_json(r):
    return _clean(r)


def block_json(b):
    return _clean(b)


def case_json(c):
    out = _clean(c)
    out["is_first_case_of_day"] = is_first_case_of_day(c)
    return out


def coverage_json(c):
    return _clean(c)


def slot_json(s):
    return _clean(s)


def request_json(r):
    return _clean(r)


def report_json(r):
    return _clean(r)


def review_json(r):
    return _clean(r)


def vote_json(v):
    return _clean(v)


def first_case_of_room_day(or_id, date):
    """Earliest-scheduled non-CANCELLED non-BUMPED case of the room-day.

    Tie-break: created_at ASC, then insertion order (stable).
    """
    cands = [
        c
        for c in db.cases.values()
        if c.get("or_id") == or_id
        and c.get("date") == date
        and c["status"] not in ("CANCELLED", "BUMPED")
        and c.get("scheduled_start_minute") is not None
    ]
    if not cands:
        return None
    cands.sort(
        key=lambda c: (c["scheduled_start_minute"], c["created_at"], c["_insert_seq"])
    )
    return cands[0]


def is_first_case_of_day(case):
    if case["status"] in ("CANCELLED", "BUMPED"):
        return False
    if case.get("scheduled_start_minute") is None:
        return False
    if not case.get("or_id") or not case.get("date"):
        return False
    first = first_case_of_room_day(case["or_id"], case["date"])
    return first is not None and first["id"] == case["id"]
