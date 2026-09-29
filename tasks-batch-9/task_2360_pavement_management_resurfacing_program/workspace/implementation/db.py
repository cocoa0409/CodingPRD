"""In-memory data store.

Every collection starts EMPTY on every boot. Nothing here seeds, preloads or
hardcodes entity data: tests build all preconditions through the API surface.
"""
import itertools
import uuid

import clock

segments = {}
surveys = {}
observations = {}
candidates = {}
scenarios = {}
allocations = {}
contractors = {}
projects = {}
project_segments = {}
coordinations = {}
cut_permits = {}
acceptance_tests = {}
service_requests = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def audit(now=None):
    """Server-managed fields shared by every resource (PRD 2.5)."""
    stamp = now or clock.now()
    return {
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next(_seq),
    }


def ordered(rows):
    """Default list ordering: created_at ascending (stable by insertion)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
