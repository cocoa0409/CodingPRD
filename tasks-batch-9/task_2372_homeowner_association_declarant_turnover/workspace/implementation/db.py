"""In-memory data store.

Every collection starts empty on every boot; nothing is seeded, preloaded or
hardcoded.  Records are plain dicts whose public keys are exactly the response
field names; internal bookkeeping keys are prefixed with "_".
"""
import itertools
import uuid

from flask import g

import util


class Store:
    def __init__(self):
        self.associations = {}
        self.turnover_cases = {}
        self.lots = {}
        self.components = {}
        self.reserve_studies = {}
        self.subsidy_entries = {}
        self.audit_engagements = {}
        self.defect_claims = {}
        self.vendor_contracts = {}
        self.records_items = {}
        self.directors = {}
        self.assessment_schedules = {}
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_record(fields):
    """Mint a record with the four system-managed properties (PRD §2.4)."""
    stamp = util.real_now_iso()
    record = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    record.update(fields)
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and advance version — once per record per request."""
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    record["updated_at"] = util.real_now_iso()
    if record["id"] not in seen:
        record["version"] += 1
        seen.add(record["id"])
    return record


def ordered(records):
    """created_at ascending — the processing order every cascade uses."""
    return sorted(records, key=lambda r: r["_seq"])


def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def serialize_list(records):
    return [serialize(r) for r in records]
