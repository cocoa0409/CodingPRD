"""In-memory store.  Starts completely empty on every boot -- nothing is seeded."""
import threading

from flask import g

import util

COLLECTIONS = (
    "groups",
    "organizers",
    "plans",
    "scenarios",
    "raises",
    "subscriptions",
    "filings",
    "conditions",
    "policies",
    "contracts",
    "windows",
    "exams",
    "deviations",
)

LOCK = threading.RLock()

STATE = {}


def reset():
    STATE.clear()
    for name in COLLECTIONS:
        STATE[name] = {}
    STATE["clock"] = util.CLOCK_START
    STATE["seq"] = 0


reset()


def clock():
    return STATE["clock"]


def set_clock(value):
    STATE["clock"] = value


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def insert(collection, row):
    row["id"] = row.get("id") or util.new_id()
    now = util.wall_now()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_seq"] = next_seq()
    STATE[collection][row["id"]] = row
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return STATE[collection].get(row_id)


def all_rows(collection):
    return sorted(STATE[collection].values(), key=lambda r: r["_seq"])


def touch(row):
    """Mark a row as mutated by this request.  Version bumps once per request."""
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = []
        g.touched = touched
    for existing in touched:
        if existing is row:
            return
    touched.append(row)


def commit():
    """Apply exactly one version bump / updated_at refresh per touched row."""
    touched = getattr(g, "touched", None)
    if not touched:
        g.touched = []
        return
    now = util.wall_now()
    for row in touched:
        row["version"] += 1
        row["updated_at"] = now
    g.touched = []


def discard():
    g.touched = []
