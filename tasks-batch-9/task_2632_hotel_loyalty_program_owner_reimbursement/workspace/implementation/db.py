"""In-memory data store, logical programme clock and common-field helpers.

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded.  The only row that exists from server start is the singleton
ProgramFund, which the PRD declares as existing from server start with a fixed
opening posture (section 3.9).
"""

import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# logical programme clock
# ---------------------------------------------------------------------------

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.hotels = {}
        self.rate_plans = {}
        self.pricing_rows = {}
        self.blackout_windows = {}
        self.members = {}
        self.stays = {}
        self.deliveries = {}
        self.redemptions = {}
        self.batches = {}
        self.ledger_entries = {}
        self.purchases = {}
        self.partners = {}
        self.complaints = {}
        self.fund = None
        self._seq = 0
        self.clock = CLOCK_EPOCH

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def set_clock(dt):
    store.clock = dt


def clock_now():
    return store.clock


def clock_date():
    return store.clock.date()


def clock_year():
    return store.clock.year


def clock_month_key():
    return "%04d-%02d" % (store.clock.year, store.clock.month)


# ---------------------------------------------------------------------------
# timestamps / ids
# ---------------------------------------------------------------------------

def iso(dt):
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(store.clock)


def new_id():
    return str(uuid.uuid4())


def parse_utc(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
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
        try:
            dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def date_str(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def day_span(start, end):
    """Inclusive day count between two calendar dates."""
    return (end - start).days + 1


def nights_between(checkin, checkout):
    return (checkout - checkin).days


def date_range_half_open(checkin, checkout):
    cur = checkin
    while cur < checkout:
        yield cur
        cur = cur + timedelta(days=1)


def year_of(datestr):
    if not isinstance(datestr, str) or len(datestr) < 4:
        return None
    try:
        return int(datestr[0:4])
    except ValueError:
        return None


def month_key_of(datestr):
    if not isinstance(datestr, str) or len(datestr) < 7:
        return None
    return datestr[0:7]


# ---------------------------------------------------------------------------
# common field helpers
# ---------------------------------------------------------------------------

_written = set()


def begin_request():
    """A row is written at most once per request, so its version moves by at
    most one no matter how many hops of one cascade touch it."""
    _written.clear()


def stamp_full(record):
    """id + created_at + updated_at + version."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = store.next_seq()
    _written.add(record["id"])
    return record


def stamp_light(record):
    """id + created_at only (RatePlan, RedemptionPricing, PointLedgerEntry)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = store.next_seq()
    return record


def touch(record):
    """Record an explicit mutation of a versioned row."""
    record["updated_at"] = now_iso()
    identifier = record.get("id")
    if identifier not in _written:
        record["version"] = record.get("version", 1) + 1
        _written.add(identifier)
    return record


def apply_derived(record, values):
    """Write re-derived fields.  Bumps updated_at/version only when a value
    actually moves, because a write that changes nothing is not a mutation."""
    changed = False
    for key, value in values.items():
        if record.get(key) != value:
            record[key] = value
            changed = True
    if changed:
        touch(record)
    return changed


def public(record):
    return dict((k, v) for k, v in record.items() if not k.startswith("_"))


def sort_key(record):
    return (record.get("created_at") or "", record.get("_seq") or 0)


def ordered(values):
    return sorted(values, key=sort_key)
