"""In-memory data store and logical clock for the IACUC & Vivarium Management API.

The store starts completely empty on every boot -- no seeding, no preloading.
All datetimes are stored internally as tz-aware UTC datetime objects and are
serialized to ISO 8601 (3 fractional digits, Z suffix) at the envelope layer.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (never wall-clock). Starts exactly at 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# ---------------------------------------------------------------------------
# Stores: dict id -> Rec. Empty at boot; tests construct all data via the API.
# ---------------------------------------------------------------------------
STORE = {
    "investigators": {},
    "grants": {},
    "personnel": {},
    "training_enrollments": {},
    "occ_health_enrollments": {},
    "protocols": {},
    "protocol_reviewers": {},
    "cages": {},
    "animals": {},
    "litters": {},
    "census_records": {},
    "billing_runs": {},
    "per_diem_charges": {},
    "inspections": {},
    "adverse_events": {},
    "deviations": {},
    "room_bookings": {},
}

_seq = 0
_protocol_seq = {}


def next_seq():
    """Monotonic insertion sequence used as a stable tiebreak for created_at."""
    global _seq
    _seq += 1
    return _seq


def mint_protocol_number():
    """IACUC-YYYY-NNNN, NNNN zero-padded sequence per logical-clock year."""
    year = _clock.year
    n = _protocol_seq.get(year, 0) + 1
    _protocol_seq[year] = n
    return f"IACUC-{year:04d}-{n:04d}"


class Rec:
    """A stored entity record (plain attribute bag)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def touch(self):
        """Mutation bookkeeping: refresh updated_at and increment version."""
        self.updated_dt = now()
        self.version += 1


def new_rec(store_name, **fields):
    r = Rec(
        id=str(uuid.uuid4()),
        created_dt=now(),
        updated_dt=now(),
        version=1,
        seq=next_seq(),
        **fields,
    )
    STORE[store_name][r.id] = r
    return r


def iso(dt):
    """Serialize a datetime to ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string to a tz-aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    t = value.strip()
    if not t:
        return None
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
