"""In-memory data store. All state lives in module-level dicts keyed by id.
The store starts completely empty on every process boot — no seeding.
The logical clock starts at exactly 2026-08-01T00:00:00Z and is only moved by
POST /vsa/_clock/set_current_utc.
"""
from datetime import datetime, timezone

# Logical clock (never reads the wall clock)
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
clock_dt = DEFAULT_CLOCK

# Monotonic insertion sequence (stable sort tiebreak for equal created_at)
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


# Entity stores: id -> dict. Internal-only fields are prefixed with "_".
policies = {}
templates = {}
vendors = {}
contacts = {}
cycles = {}
responses = {}
artifacts = {}
exceptions = {}
plans = {}
acceptances = {}
addenda = {}
alerts = {}
subprocessors = {}
attestations = {}
schedules = {}
