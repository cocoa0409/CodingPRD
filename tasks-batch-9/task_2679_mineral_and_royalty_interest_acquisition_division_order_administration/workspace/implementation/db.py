"""In-memory data store, id minting, audit columns and the logical clock.

Storage is process-local Python dicts keyed by id.  Nothing is ever seeded:
every row in every collection is created by an API call.  The store therefore
starts completely empty on every boot, which is what the per-test-server
isolation of the harness requires.
"""

import datetime
import itertools
import re
import uuid

# The logical clock reads exactly this instant before any adjustment (PRD 2.4).
DEFAULT_CLOCK = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

_seq_counter = itertools.count(1)


def next_seq():
    """Monotonic insertion sequence, used as the deterministic created_at tie-break."""
    return next(_seq_counter)


def new_id():
    """Server-minted UUID identity with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


class Store(object):
    def __init__(self):
        self.tracts = {}
        self.chain_entries = {}
        self.royalty_owners = {}
        self.mineral_interests = {}
        self.valuations = {}
        self.offer_letters = {}
        self.psas = {}
        self.title_defects = {}
        self.units = {}
        self.allocations = {}
        self.division_orders = {}
        self.revenue_details = {}
        self.suspense_accounts = {}
        self.clock = DEFAULT_CLOCK


db = Store()


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------
def iso_ms(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso_ms(datetime.datetime.now(datetime.timezone.utc))


def clock_dt():
    return db.clock


def clock_iso():
    return iso_ms(db.clock)


def clock_date():
    return db.clock.date()


def clock_date_str():
    d = db.clock
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def clock_ym():
    return "%04d-%02d" % (db.clock.year, db.clock.month)


_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO 8601 instant; returns an aware datetime in UTC or None."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    offset = datetime.timedelta(0)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = sign * datetime.timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    try:
        naive = datetime.datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    return (naive - offset).replace(tzinfo=datetime.timezone.utc)


# --------------------------------------------------------------------------
# audit columns
# --------------------------------------------------------------------------
def stamp_new(record):
    """Attach id and the four common properties to a brand-new row."""
    record["id"] = new_id()
    record["_seq"] = next_seq()
    ts = now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def stamp_new_immutable(record):
    """A TitleChainEntry carries only id and created_at (PRD 2.4)."""
    record["id"] = new_id()
    record["_seq"] = next_seq()
    record["created_at"] = now_iso()
    return record


def touch(record):
    """Refresh updated_at and increment version by exactly 1."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def by_seq_desc(rows):
    return sorted(rows, key=lambda r: r["_seq"], reverse=True)
