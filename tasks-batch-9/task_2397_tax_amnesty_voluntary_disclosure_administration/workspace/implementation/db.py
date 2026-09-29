"""In-memory data store.

The store starts completely empty on every boot: no entity is seeded,
preloaded or hardcoded anywhere.  Every row is created through the declared
API surface.
"""

import itertools
import uuid

import clock

_seq = itertools.count(1)

# One dict per entity, keyed by id.
programs = {}
tax_type_terms = {}
taxpayers = {}
enforcement_cases = {}
representatives = {}
pre_clearances = {}
negotiation_rounds = {}
agreements = {}
returns = {}
payment_plans = {}
installments = {}
payments = {}
enforcement_actions = {}


def new_id():
    return str(uuid.uuid4())


def insert(collection, fields, versioned=True):
    """Create a row with the system audit fields (PRD 2.4)."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = clock.now_iso()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = next(_seq)
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and advance version by exactly one."""
    if "version" in rec:
        rec["updated_at"] = clock.now_iso()
        rec["version"] = rec["version"] + 1
    return rec


def ordered(rows):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
