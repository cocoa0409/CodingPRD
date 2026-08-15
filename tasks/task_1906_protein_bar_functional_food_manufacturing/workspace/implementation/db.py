"""In-memory data store. The store starts EMPTY on every boot — no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

# One dict per entity type, keyed by id.
STORES = {
    "suppliers": {},
    "ingredients": {},
    "lots": {},
    "customers": {},
    "agreements": {},
    "formulas": {},
    "revisions": {},
    "lines": {},
    "slots": {},
    "runs": {},
    "changeovers": {},
    "studies": {},
    "pulls": {},
    "releases": {},
    "retains": {},
    "claims": {},
}

# Monotonic creation sequence (stable created order for list sorting / ties).
_seq = itertools.count(1)

# Run counter for batch_code minting (1-based count of previously created runs).
_run_counter = itertools.count(1)


class LogicalClock:
    """The plant logical clock. Starts at exactly 2026-08-01T00:00:00Z and
    never falls back to wall-clock time."""

    def __init__(self):
        self.current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def set(self, dt):
        self.current = dt


CLOCK = LogicalClock()


def new_seq():
    return next(_seq)


def new_run_number():
    return next(_run_counter)


def wall_now():
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_ts(wall_now())


def fmt_dt(dt):
    """Business datetime output: UTC, 'Z' suffix, millis only when present."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id():
    return str(uuid.uuid4())


def base_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": new_seq(),
    }


def touch(rec):
    """Mutation bookkeeping: version +1 and updated_at refresh."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}
