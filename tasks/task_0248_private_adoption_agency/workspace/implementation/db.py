"""In-memory data store. Starts EMPTY on every boot — no seeding, no preload.

Every entity is created by tests via the declared API surface. There is no
SQLite file, no JSON dump, no external persistence. State lives only in these
module-level dicts for the lifetime of the process.
"""
import itertools
import threading
import uuid

# One dict per entity type, keyed by the entity's string id (UUID, no prefix).
agencies = {}
cases = {}
families = {}
home_studies = {}
birth_parents = {}
counseling_sessions = {}
matches = {}
consent_records = {}
icpc_clearances = {}
placements = {}
post_placement_visits = {}
expense_entries = {}
escrow_transactions = {}
agency_fee_invoices = {}

# Monotonic sequence to provide a stable creation order independent of
# timestamp collisions (multiple creates can land on the same millisecond).
_seq_counter = itertools.count(1)

# A single global lock makes every request handler atomic with respect to the
# in-memory store, which is what the OCC / cascade semantics rely on.
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)
