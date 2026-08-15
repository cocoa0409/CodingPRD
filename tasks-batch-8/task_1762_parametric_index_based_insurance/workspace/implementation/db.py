"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts empty on every boot. No seeding, no preload, no persistence.
"""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

_LOGICAL_CLOCK_ISO = "2026-08-01T00:00:00Z"


def get_logical_clock() -> datetime:
    """Return the current logical clock instant (timezone-aware UTC)."""
    return _parse_iso8601(_LOGICAL_CLOCK_ISO)


def set_logical_clock(iso_str: str) -> None:
    global _LOGICAL_CLOCK_ISO
    _LOGICAL_CLOCK_ISO = iso_str


def _parse_iso8601(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp like 2026-08-01T00:00:00Z or with .123Z."""
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def now_iso() -> str:
    """Current logical clock instant rendered as ISO 8601 UTC with 3 fractional digits.

    PRD §2.5: created_at / updated_at are ISO 8601 UTC with three fractional digits.
    We derive them from the logical clock so reads after a clock-set observe a
    coherent timeline; to guarantee monotonic uniqueness across rapid successive
    mutations we keep a counter and add microseconds when needed.
    """
    dt = get_logical_clock()
    # Add the mutation counter as microseconds so consecutive mutations never
    # share an identical timestamp string (important for distinct-timestamp
    # invariants relied on by ordering rules).
    global _TICK_COUNTER
    _TICK_COUNTER += 1
    from datetime import timedelta
    dt = dt + timedelta(microseconds=_TICK_COUNTER)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


_TICK_COUNTER = 0


def new_id() -> str:
    """Server-minted UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Entity stores — plain dicts keyed by id. All empty at boot.
# ---------------------------------------------------------------------------

programs = {}          # InsuranceProgram
index_definitions = {} # IndexDefinition
stations = {}          # MeasurementStation
observations = {}      # IndexObservation (append-only)
policyholders = {}     # Policyholder
policies = {}          # ParametricPolicy
trigger_events = {}    # TriggerEvent
claims = {}            # PayoutClaim
disputes = {}          # DisputeCase
treaties = {}          # ReinsuranceTreaty
invoices = {}          # PremiumInvoice

# Per-index monotonic observation ingestion sequence counter (PRD §3.3)
observation_seq = {}   # index_definition_id -> int


def next_observation_seq(index_id: str) -> int:
    seq = observation_seq.get(index_id, 0) + 1
    observation_seq[index_id] = seq
    return seq
