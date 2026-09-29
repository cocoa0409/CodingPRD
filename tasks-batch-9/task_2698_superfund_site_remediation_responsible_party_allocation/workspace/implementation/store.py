"""In-memory datastore.

Every collection boots empty on every process start: the implementation never
seeds, preloads or hardcodes a single record.  Tests build all state through
the declared endpoints.
"""

import itertools
import uuid

sites = {}
prps = {}
ownership_periods = {}
waste_in_records = {}
remedial_investigations = {}
contaminant_samples = {}
remedy_alternatives = {}
records_of_decision = {}
allocation_rounds = {}
allocation_shares = {}
consent_decrees = {}
remediation_contracts = {}
work_windows = {}
cost_recovery_actions = {}

# Oversight postings are not a declared entity: they are the audit trail the
# oversight calculation re-derives oversight_direct_cents from on every posting.
oversight_postings = {}

_counter = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion counter, the final tie-break of every ordering."""
    return next(_counter)
