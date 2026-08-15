"""In-memory data store.

All state lives in module-level dicts keyed by id. The store starts empty on
every boot; nothing is seeded here. A single process-wide RLock guards every
request so concurrent requests cannot interleave multi-step cascades.

The logical clock boots at exactly 2026-08-01T00:00:00Z and never falls back
to wall-clock time (PRD section 2.5). Every server-generated timestamp in the
system is derived from this logical clock.
"""

import threading
from datetime import datetime, timezone

_logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

lock = threading.RLock()

agencies = {}            # Agency
agents = {}              # Agent
clients = {}             # Client
teams = {}               # Team
cap_seasons = {}         # CapSeason
contracts = {}           # Contract
proposals = {}           # Proposal
endorsements = {}        # EndorsementDeal
tender_options = {}      # TenderOption
grievances = {}          # Grievance
fee_ledger_entries = {}  # FeeLedgerEntry


def get_clock():
    return _logical_clock


def set_clock(dt):
    global _logical_clock
    _logical_clock = dt
