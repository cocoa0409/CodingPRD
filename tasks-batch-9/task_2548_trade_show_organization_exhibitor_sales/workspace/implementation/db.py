"""In-memory store and logical clock.

Storage is process-local Python dicts only. Every boot starts completely
empty -- nothing is seeded, preloaded or hardcoded here.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.3: the logical clock starts at this instant on every boot.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

STORE_NAMES = (
    "venue_contracts",
    "shows",
    "booths",
    "exhibitors",
    "selection_appointments",
    "space_contracts",
    "service_orders",
    "rule_violations",
    "sponsorship_packages",
    "sponsorship_deals",
    "fulfillment_obligations",
    "registrations",
    "lead_scans",
)


class DB(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in STORE_NAMES:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def now():
    return db.clock


def today():
    return db.clock.date()


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        pass
    dt = parse_dt(text)
    if dt is None:
        return None
    return dt.date()


def add_days(d, days):
    return d + timedelta(days=days)


def base_row():
    """Common system fields shared by every versioned entity (PRD 2.4)."""
    stamp = fmt_dt(now())
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def append_only_row():
    """LeadScan carries only an id and created_at (PRD 2.4)."""
    return {
        "id": new_id(),
        "created_at": fmt_dt(now()),
        "_seq": db.next_seq(),
    }


def touch(row):
    """Record a mutation: refresh updated_at and increment version."""
    row["updated_at"] = fmt_dt(now())
    row["version"] = row.get("version", 1) + 1
    return row


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def by_created(rows):
    return sorted(rows, key=sort_key)
