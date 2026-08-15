"""Shared lookups and mutation helpers."""
from db import STORE, touch
from errors import not_found


def get(coll, rid):
    e = STORE[coll].get(rid)
    if e is None:
        raise not_found("Resource not found: %s" % rid)
    return e


def find(coll, **kw):
    out = []
    for e in STORE[coll].values():
        if all(e.get(k) == v for k, v in kw.items()):
            out.append(e)
    return out


def find_all(coll, pred):
    return [e for e in STORE[coll].values() if pred(e)]


def find_one(coll, pred):
    for e in STORE[coll].values():
        if pred(e):
            return e
    return None


def protocol_for_case(case_id):
    return find_one("rtp_protocols", lambda p: p["injury_case_id"] == case_id)


def current_entries_for_case(case_id):
    return find_all("daily_status_entries",
                    lambda e: e["injury_case_id"] == case_id and e["is_current"])


def latest_current_entry(case_id):
    """is_current entry with max entry_date (tie: latest created_at)."""
    entries = current_entries_for_case(case_id)
    if not entries:
        return None
    entries.sort(key=lambda e: (e["_entry_date"], e["created_at"]))
    return entries[-1]


def today_current_entry(case_id, today):
    for e in current_entries_for_case(case_id):
        if e["_entry_date"] == today:
            return e
    return None
