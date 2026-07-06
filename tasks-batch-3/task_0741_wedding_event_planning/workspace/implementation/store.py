"""In-memory data store. Fresh (empty) on every process boot. No seeding."""
import itertools
import uuid

from util import now_iso, parse_dt

# --- entity collections keyed by id ---
events = {}
contracts = {}
vendors = {}
cois = {}
bookings = {}
payments = {}
timeline_blocks = {}
guests = {}
tables = {}
seat_assignments = {}
staff_members = {}
staff_assignments = {}

# --- logical clock (default per PRD 2.6) ---
CLOCK_DEFAULT_RAW = "2026-03-01T00:00:00Z"
clock_dt = parse_dt(CLOCK_DEFAULT_RAW)
clock_raw = CLOCK_DEFAULT_RAW

# --- monotonic insertion sequence for stable created_at ordering ---
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_common():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Register a mutation: refresh updated_at, bump version."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def serialize(entity):
    """Public representation: drop internal (underscore-prefixed) keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
