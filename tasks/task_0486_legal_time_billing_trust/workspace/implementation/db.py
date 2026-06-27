"""In-memory data store. All state lives in process-local dicts keyed by id.

A fresh process (start.sh re-invocation) wipes every byte of state — there is
NO seeding, preloading, or hardcoded entity data here. Tests build every entity
through the declared API surface.

Each entity carries `created_at` (ISO string) for display plus a hidden monotone
`_seq` integer used as the canonical creation-order / tie-break key so that
ordering is deterministic even when two records share a millisecond timestamp.
"""

import threading
import uuid

# One lock guards all mutations so multi-step operations stay atomic under the
# per-test-server harness (single process, threaded Flask dev server).
LOCK = threading.RLock()

# Entity tables, each id -> dict.
clients = {}
timekeepers = {}
matters = {}
conflict_checks = {}
time_entries = {}
expense_entries = {}
billing_codes = {}
invoices = {}
trust_accounts = {}
client_trust_ledgers = {}
retainer_holds = {}
trust_transactions = {}
payments = {}
rate_overrides = {}  # client rate overrides (lean: id, client_id, role_kind, rate_cents)

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


def get_or_404(table, _id):
    """Return the record or None (caller raises the not-found error)."""
    return table.get(_id)
