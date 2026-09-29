"""In-memory data store, id minting, timestamp helpers and the logical clock.

The store is created empty on every boot.  Nothing is ever seeded here: every
entity is built by callers through the declared HTTP surface.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.4: the logical clock starts at exactly this instant and never falls
# back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.buyers = {}
        self.programs = {}
        self.sessions = {}
        self.suppliers = {}
        self.bank_accounts = {}
        self.files = {}
        self.invoices = {}
        self.invoice_lines = {}
        self.disputes = {}
        self.offers = {}
        self.funders = {}
        self.commitments = {}
        self.payments = {}
        self.advices = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    """Server minted UUID, no prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_iso():
    return fmt_dt(wall_now())


def parse_dt(raw):
    """Parse an ISO 8601 instant into a naive UTC datetime, or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def clock():
    return db.clock


def clock_date():
    return db.clock.date()


def clock_iso():
    return fmt_dt(db.clock)


def date_midnight(d):
    return datetime(d.year, d.month, d.day)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def base_row(common=True):
    """Common system fields.  `common=False` for the three kinds that carry
    only id + created_at (ApprovedPayableFile, InvoiceLine, RemittanceAdvice)."""
    stamp = now_iso()
    row = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at and bump version by one."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1


def put_dt(row, key, dt, raw=None):
    """Store a datetime field: public ISO string plus a private parsed value."""
    if dt is None and raw is None:
        row[key] = None
        row["_" + key] = None
        return
    row[key] = raw if raw is not None else fmt_dt(dt)
    row["_" + key] = dt


def order_key(row):
    """created_at ASC, ties broken by creation sequence (never by id)."""
    return (row["created_at"], row["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=order_key)


def public(row):
    if row is None:
        return None
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))
