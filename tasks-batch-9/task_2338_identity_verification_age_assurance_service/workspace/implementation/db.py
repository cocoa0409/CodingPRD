"""In-memory data store.

Every collection is a plain dict keyed by the resource id. The store starts empty on
every boot: no entity is ever seeded, preloaded or hardcoded here. Tests build all
preconditions through the declared API surface.
"""
import itertools
import uuid

from flask import g, has_request_context

import clock

CLIENTS = {}
METHOD_PROFILES = {}
POLICIES = {}
SESSIONS = {}
ATTEMPTS = {}
DOCUMENT_CAPTURES = {}
LIVENESS_CHECKS = {}
BIOMETRIC_TEMPLATES = {}
AGE_RESULTS = {}
PATHWAYS = {}
REVIEW_CASES = {}
BIAS_AUDITS = {}
COHORT_METRICS = {}
AUDIT_EVENTS = {}

ALL_COLLECTIONS = (
    CLIENTS, METHOD_PROFILES, POLICIES, SESSIONS, ATTEMPTS, DOCUMENT_CAPTURES,
    LIVENESS_CHECKS, BIOMETRIC_TEMPLATES, AGE_RESULTS, PATHWAYS, REVIEW_CASES,
    BIAS_AUDITS, COHORT_METRICS, AUDIT_EVENTS,
)

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def insert(collection, record, versioned=True):
    """Insert a record, stamping id, ordering sequence and the common fields."""
    record.setdefault("id", new_id())
    record["_seq"] = next(_seq)
    record["created_at"] = clock.now()
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    collection[record["id"]] = record
    return record


def touch(record):
    """Mark a record as mutated: refresh updated_at and bump version once per request."""
    if record is None or "version" not in record:
        return record
    if has_request_context():
        touched = getattr(g, "_touched", None)
        if touched is None:
            touched = set()
            g._touched = touched
        key = id(record)
        if key in touched:
            return record
        touched.add(key)
    record["updated_at"] = clock.now()
    record["version"] = record["version"] + 1
    return record


def get(collection, record_id):
    if not isinstance(record_id, str):
        return None
    return collection.get(record_id)


def ordered(records):
    """Default ordering: created_at ascending, insertion order as the stable tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def all_of(collection):
    return ordered(list(collection.values()))
