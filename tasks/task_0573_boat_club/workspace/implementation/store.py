"""In-memory data store. Fresh (empty) on every process boot. No seeding."""
import itertools
import uuid

from util import now_iso, parse_dt, fmt_dt

# --- entity collections keyed by id (empty at boot; never seeded) ---
docks = {}
tiers = {}          # keyed by tier_code (== id)
members = {}
boats = {}
reservations = {}
sessions = {}
enrollments = {}
damage_reports = {}
fees = {}
invoices = {}

# --- logical clock (default per PRD 2.5) ---
CLOCK_DEFAULT_RAW = "2026-05-01T00:00:00Z"
clock_dt = parse_dt(CLOCK_DEFAULT_RAW)

# --- monotonic insertion sequence for stable created_at ordering / tie-breaks ---
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def clock_iso():
    """Current logical clock formatted as ISO 8601 UTC, 3 fractional digits."""
    return fmt_dt(clock_dt)


def new_common():
    """Common system fields for full entities (all but MembershipTier)."""
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Register a mutation: refresh updated_at, bump version by one."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def serialize(entity):
    """Public representation: drop internal (underscore-prefixed) keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
