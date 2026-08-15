"""In-memory data store, logical clock, and ID/timestamp helpers.

Storage is in-memory only (dicts keyed by id). The store starts empty on every
boot — no seeding. The logical clock defaults to 2026-08-01T00:00:00Z and is
set only via POST /completion/_clock/set_current_utc.
"""
import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.customers = {}
        self.aircraft = {}
        self.programs = {}
        self.paint_schemes = {}
        self.surface_assessments = {}
        self.discovery_items = {}
        self.change_orders = {}
        self.hangar_bays = {}
        self.hangar_slots = {}
        self.paint_booths = {}
        self.booth_bookings = {}
        self.soft_good_lots = {}
        self.burn_tests = {}
        self.weight_records = {}
        self.quality_inspections = {}
        self.delay_events = {}
        self.invoices = {}
        # Global monotone insertion sequence (tiebreak for created_at sorting).
        self.seq = itertools.count(1)
        # Logical clock — startup default per PRD §2.4.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(STORE.seq)


def now_dt():
    """Current logical-clock instant (used for entity timestamps and rules)."""
    return STORE.clock


def set_clock(dt):
    STORE.clock = dt


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(STORE.clock)


def wall_iso():
    """Wall-clock timestamp for the response meta wrapper."""
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
