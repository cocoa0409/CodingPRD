"""In-memory data store.

The store starts empty on every boot.  No entity is seeded, preloaded, or
hardcoded; every resource is created through the declared API surface.
Each record carries a hidden monotonic `_seq` used only as a stable final
tie-break where the PRD pins ordering by timestamps (which can coincide under
the logical clock); resource ids are never used for ordering.
"""
import uuid

seasons = {}
programs = {}
rooms = {}
instructors = {}
sessions = {}
meetings = {}
contracts = {}
households = {}
participants = {}
safety_forms = {}
applications = {}
registrations = {}
payments = {}
attendance = {}

_seq_counter = [0]


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]
