"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every boot. No seeding, no preloading, ever.
The logical clock starts at exactly 2026-08-01T00:00:00Z and never falls
back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id)
# ---------------------------------------------------------------------------

lines = {}                # ProcessingLine
shifts = {}               # ProductionShift
sanitation_runs = {}      # SanitationRun
preop_inspections = {}    # PreOpInspection
waivers = {}              # LineSpeedWaiver
flock_lots = {}           # FlockLot
line_runs = {}            # LineRun
condemnation_records = {}  # CondemnationRecord
utility_readings = {}     # UtilityMeterReading (append-only)
orders = {}               # ProductOrder
deboning_batches = {}     # DeboningBatch
finished_lots = {}        # FinishedLot
chill_chain_logs = {}     # ChillChainLog (append-only)


# ---------------------------------------------------------------------------
# Logical clock — starts at exactly 2026-08-01T00:00:00Z
# ---------------------------------------------------------------------------

_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current_utc = _CLOCK_START


def clock_now():
    """Return the current logical-clock instant (timezone-aware UTC)."""
    return _current_utc


def set_clock(dt):
    """Advance the logical clock to the given aware datetime."""
    global _current_utc
    _current_utc = dt


def new_id():
    """Mint a unique id (UUID4, no type prefix)."""
    return str(uuid.uuid4())
