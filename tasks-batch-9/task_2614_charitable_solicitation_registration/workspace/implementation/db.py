"""In-memory data store.

Every collection is a plain dict keyed by the row's ``id`` (``state_profiles``
is keyed by its natural key, ``state_code``).  The store starts empty on every
boot: no entity is ever seeded, preloaded or hardcoded.  Callers construct all
state through the declared API surface.
"""
import itertools
import uuid

from flask import g

import clock

_seq = itertools.count(1)


class Store(object):
    def __init__(self):
        self.organizations = {}
        self.state_profiles = {}          # keyed by state_code
        self.solicitation_activities = {}
        self.financial_statements = {}
        self.officer_disclosures = {}
        self.state_registrations = {}
        self.registration_documents = {}
        self.extension_requests = {}
        self.professional_fundraisers = {}
        self.fundraiser_registrations = {}
        self.fundraising_contracts = {}
        self.coventure_promotions = {}
        self.disclosure_statements = {}
        self.enforcement_actions = {}


db = Store()


def new_id():
    """A bare UUID with no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion sequence, used as the tie-breaker for created_at."""
    return next(_seq)


def stamp_new(record, common_fields=True):
    """Mint id / created_at, and updated_at + version when the entity carries them.

    ``SolicitationActivity`` is the single entity that carries id and created_at
    only (PRD 2.5), so it is created with ``common_fields=False``.
    """
    record["id"] = new_id()
    record["created_at"] = clock.now_iso()
    if common_fields:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Refresh updated_at and increment version by exactly one."""
    record["updated_at"] = clock.now_iso()
    record["version"] = int(record.get("version", 1)) + 1
    return record


def touch_once(record, kind):
    """Increment ``version`` at most once per request for this row.

    A single client request can legitimately drive several cascade links across
    the same row (for instance a financial restatement repoints a filing and
    then pushes it back to DEFICIENT).  PRD 2.5 fixes ``version`` as
    incrementing by exactly one per mutation of a row, so the cascade bookkeeping
    is collapsed to one increment per row per request.
    """
    key = (kind, record["id"])
    seen = getattr(g, "_touched_rows", None)
    if seen is None:
        seen = set()
        g._touched_rows = seen
    if key in seen:
        return record
    seen.add(key)
    return touch(record)


def sorted_rows(rows):
    """Default ordering for every list endpoint: created_at ascending.

    The logical clock is frozen between administrator moves, so ``created_at``
    ties are the norm; the insertion sequence breaks them deterministically.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(record):
    """Strip internal bookkeeping keys from a stored row."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}
