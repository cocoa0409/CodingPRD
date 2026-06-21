"""In-memory data store.

All state lives in module-level dicts keyed by id. The process is restarted by
the test harness before every test (start.sh re-invocation), so a fresh import
of this module is an empty store. Nothing is seeded at startup.
"""
import uuid
from datetime import datetime, timezone

# ---- Collections (keyed by id) ----------------------------------------------
commodity_programs = {}
policies = {}
coverage_elections = {}
units = {}
acreage_reports = {}
loss_claims = {}
prevented_planting_claims = {}
agent_commissions = {}
producers = {}
agents = {}

# Ordered list of all collections so reset is exhaustive.
_ALL = [
    commodity_programs,
    policies,
    coverage_elections,
    units,
    acreage_reports,
    loss_claims,
    prevented_planting_claims,
    agent_commissions,
    producers,
    agents,
]

# ---- Monotonic creation counter for stable created_at ordering --------------
# created_at is an ISO timestamp, but multiple resources can be created within
# the same millisecond. We keep a monotonic sequence to make sort-by-created_at
# deterministic (ascending insertion order).
_seq = 0

# ---- Server clock -----------------------------------------------------------
# None means "use the real wall clock"; once set via /_clock/set_current_utc it
# holds an aware UTC datetime that all temporal checks use as "now".
_server_now = None


def reset():
    for c in _ALL:
        c.clear()
    global _seq, _server_now
    _seq = 0
    _server_now = None


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    global _seq
    _seq += 1
    return _seq


def set_server_now(dt):
    global _server_now
    _server_now = dt


def server_now():
    """Return the current server 'now' as an aware UTC datetime."""
    if _server_now is not None:
        return _server_now
    return datetime.now(timezone.utc)
