"""In-memory data store with dict-keyed collections per entity."""
import threading
import uuid

from clock import get_now, format_iso


_lock = threading.RLock()


# Each table is a dict id -> row
crew_members = {}
pairings = {}
duty_periods = {}      # id -> DutyPeriod
flight_legs = {}       # id -> FlightLeg
bids = {}
assignments = {}
reserve_pool = {}
sick_calls = {}
trade_requests = {}

# Auxiliary structures
# union_blessings: trade_id -> set of union_local_id strings
union_blessings = {}
# Awarded bid windows (set of bid_window_id strings already swept successfully)
awarded_bid_windows = set()


def lock():
    return _lock


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return format_iso(get_now())


def init_common(row: dict, with_top_level=True):
    """Initialize common fields. Top-level entities get updated_at + version."""
    ts = now_iso()
    if "id" not in row:
        row["id"] = new_id()
    row["created_at"] = ts
    if with_top_level:
        row["updated_at"] = ts
        row["version"] = 1
    return row


def touch(row: dict):
    """Bump updated_at + version on a top-level aggregate."""
    if "version" in row:
        row["version"] = int(row["version"]) + 1
        row["updated_at"] = now_iso()


def reset_all():
    """Wipe the store — useful for tests if needed."""
    with _lock:
        crew_members.clear()
        pairings.clear()
        duty_periods.clear()
        flight_legs.clear()
        bids.clear()
        assignments.clear()
        reserve_pool.clear()
        sick_calls.clear()
        trade_requests.clear()
        union_blessings.clear()
        awarded_bid_windows.clear()
