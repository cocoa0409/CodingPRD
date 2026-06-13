"""In-memory data store.

Every byte of state lives in module-level dicts keyed by id. There is no disk
persistence; a fresh process boot (start.sh re-invocation) wipes everything.
The store starts EMPTY — no entity is seeded at import or startup.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Collections — one dict per entity, keyed by string UUID id.
# ---------------------------------------------------------------------------
corridors = {}
fx_rates = {}
senders = {}
recipients = {}
quotes = {}
transfers = {}
compliance_cases = {}
sanctions_list = {}      # SanctionsListEntry
sanctions_hits = {}
payout_attempts = {}
refunds = {}
ledger_entries = {}

# Monotonic insertion sequence, used as a stable tiebreaker for ordering when
# two records share an identical created_at timestamp (the logical clock can
# stamp many records at the same instant).
_seq_counter = 0

# The administrator-controlled logical clock. Defaults to real UTC now until an
# admin sets/advances it. Stored as a timezone-aware datetime.
_clock = datetime.now(timezone.utc)


def reset():
    """Wipe all state. Used only for defensive re-init; not called at runtime."""
    global _seq_counter, _clock
    for coll in (corridors, fx_rates, senders, recipients, quotes, transfers,
                 compliance_cases, sanctions_list, sanctions_hits,
                 payout_attempts, refunds, ledger_entries):
        coll.clear()
    _seq_counter = 0
    _clock = datetime.now(timezone.utc)


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def advance_clock(seconds):
    global _clock
    from datetime import timedelta
    _clock = _clock + timedelta(seconds=seconds)
