"""In-memory data store. Dictionaries keyed by id; the store starts empty on
every boot. No persistence of any kind, and no seeding.

Each entity dict carries a hidden `_seq` field: a global monotone creation
counter used for deterministic `created_at`-ascending ordering and ranking
tie-breaks (created_at values can coincide because timestamps come from the
logical clock).
"""
import itertools
import uuid

from clock import logical_now
from util import fmt_iso

turnarounds = {}
work_items = {}
dependencies = {}
contractors = {}
workers = {}
shifts = {}
assignments = {}
permits = {}
isolations = {}
discoveries = {}
laydown_areas = {}
reservations = {}
daily_reports = {}
punch_items = {}

_seq = itertools.count(1)


def mint_id():
    return str(uuid.uuid4())


def now_iso():
    return fmt_iso(logical_now())


def create(store, fields):
    """Insert a new entity. Callers provide id/created_at/updated_at/version."""
    entity = dict(fields)
    entity["_seq"] = next(_seq)
    store[entity["id"]] = entity
    return entity


def touch(entity):
    """Standard mutation bookkeeping: version += 1, updated_at refreshed."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def public(entity):
    """Strip internal bookkeeping fields for serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
