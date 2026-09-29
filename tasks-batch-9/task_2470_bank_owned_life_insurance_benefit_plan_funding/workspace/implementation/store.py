"""In-memory data store.

Every collection starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded; all state is created by clients through the declared endpoints.
"""

from datetime import datetime
from decimal import Decimal

from flask import g

from util import UTC, format_datetime, new_id

# PRD 2.5: before the logical clock is set for the first time it reads exactly
# 2026-08-01T00:00:00Z and never falls back to real wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "capital_positions",
    "carriers",
    "product_types",
    "diligence_reviews",
    "employees",
    "consent_records",
    "purchase_requests",
    "policies",
    "policy_valuations",
    "nqdc_plans",
    "nqdc_liabilities",
    "death_claims",
    "beneficiary_allocations",
    "exchange_analyses",
    "risk_assessments",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = CLOCK_EPOCH

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = Store()


def create_record(collection, fields, versioned=True):
    """Mint a record with server-owned identity/common fields."""
    rec = {"id": new_id(), "created_at": db.now()}
    if versioned:
        rec["updated_at"] = db.now()
        rec["version"] = 1
    rec.update(fields)
    rec["_seq"] = db.next_seq()
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """Bump version exactly once per resource per request (PRD 2.10)."""
    if rec is None:
        return rec
    if "version" not in rec:
        return rec
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = (id(rec), rec.get("id"))
    if key in touched:
        rec["updated_at"] = db.now()
        return rec
    touched.add(key)
    rec["version"] = int(rec["version"]) + 1
    rec["updated_at"] = db.now()
    return rec


def ordered(records):
    """PRD 2.3: list results are ordered by created_at ascending."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, Decimal):
            out[key] = float(value)
        elif isinstance(value, datetime):
            out[key] = format_datetime(value)
        else:
            out[key] = value
    return out


def serialize_all(records):
    return [serialize(r) for r in records]
