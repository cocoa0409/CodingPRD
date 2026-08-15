"""In-memory data store and logical program clock.

Storage is purely in-memory (dicts keyed by id). The store starts empty on
every boot; every entity is created via the declared API endpoints.
"""
import itertools
from datetime import datetime

STORE = {
    "establishments": {},
    "interceptors": {},
    "inspections": {},
    "violations": {},
    "manifests": {},
    "haulers": {},
    "disposals": {},
    "blockages": {},
    "variances": {},
    "campaigns": {},
    "outreach_events": {},
}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


# Logical program clock. Before any clock-setting call it reads exactly
# 2026-08-01T00:00:00Z (never the wall clock). Naive UTC datetime, second
# precision.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0)
_clock = {"now": INITIAL_CLOCK}


def now():
    return _clock["now"]


def set_now(value):
    _clock["now"] = value
