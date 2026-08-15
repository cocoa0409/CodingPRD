"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts empty on every boot: no seeding, no preloading, no on-disk
persistence. Every entity is constructed through the declared API surface.
"""
import itertools
import uuid

bins = {}
lots = {}
readings = {}
alerts = {}
fumigations = {}
permits = {}
contracts = {}
loadouts = {}
applicators = {}
policies = {}
claims = {}
assessments = {}
shrink_events = {}

_seq = itertools.count(1)


def new_id() -> str:
    return str(uuid.uuid4())


def next_seq() -> int:
    """Monotonic insertion sequence for deterministic tie-breaking."""
    return next(_seq)
