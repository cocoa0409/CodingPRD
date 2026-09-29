"""In-memory data store. Starts empty on every boot; nothing is ever seeded."""

import itertools
import threading
import uuid

from flask import g

import util
from constants import DEFAULT_CLOCK

_seq = itertools.count(1)
lock = threading.RLock()


class Store(object):
    def __init__(self):
        self.disciplines = {}
        self.programs = {}
        self.terms = {}
        self.faculty_members = {}
        self.credential_records = {}
        self.credential_evaluations = {}
        self.course_sections = {}
        self.course_assignments = {}
        self.justifications = {}
        self.rosters = {}
        self.contracts = {}
        self.pd_records = {}
        self.reviews = {}
        # Logical clock: parsed instant plus the literal text to echo back.
        self.clock_dt = util.parse_datetime(DEFAULT_CLOCK)
        self.clock_text = DEFAULT_CLOCK


store = Store()


def new_row(**fields):
    stamp = util.now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = next(_seq)
    return row


def touch(row):
    """Bump updated_at/version at most once per request for a given row."""
    if row is None:
        return row
    try:
        touched = g.touched
    except Exception:
        touched = None
    key = id(row)
    if touched is not None:
        if key in touched:
            row["updated_at"] = util.now_iso()
            return row
        touched.add(key)
    row["updated_at"] = util.now_iso()
    row["version"] = row.get("version", 0) + 1
    return row


def ordered(collection):
    """All rows of a collection in created_at ascending order."""
    return sorted(collection.values(), key=lambda r: r["_seq"])
