"""In-memory data store, logical clock and fiscal-calendar helpers.

The store begins completely empty on every boot; nothing is ever seeded.
"""

import re
import uuid
from datetime import date, datetime, timedelta, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.licensees = {}
        self.categories = {}
        self.clubs = {}
        self.players = {}
        self.marks = {}
        self.agreements = {}
        self.grants = {}
        self.submissions = {}
        self.sample_reviews = {}
        self.authorizations = {}
        self.reports = {}
        self.engagements = {}
        self.enforcements = {}
        self.runs = {}
        self.club_distributions = {}
        self.closed_quarters = set()
        self.clock = CLOCK_DEFAULT


S = Store()


# --------------------------------------------------------------------------- #
# identity / timestamps                                                       #
# --------------------------------------------------------------------------- #

def new_id():
    return str(uuid.uuid4())


def iso(dt):
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def clock_now():
    return S.clock


def now_iso():
    return iso(S.clock)


def clock_date():
    return S.clock.date()


def base_row(versioned=True):
    row = {"id": new_id(), "created_at": now_iso()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] += 1


def apply_changes(row, changes):
    """Apply changes; bump updated_at/version only when something moved."""
    changed = False
    for key, value in changes.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


# --------------------------------------------------------------------------- #
# shape parsing helpers                                                       #
# --------------------------------------------------------------------------- #

QUARTER_RE = re.compile(r"^\d{4}Q[1-4]$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?[Zz]$"
)


def is_quarter(value):
    return isinstance(value, str) and bool(QUARTER_RE.match(value))


def parse_date(value):
    """Return a date for a well formed YYYY-MM-DD string, else None."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_instant(value):
    if not isinstance(value, str) or not INSTANT_RE.match(value):
        return None
    body = value[:-1]
    try:
        if "." in body:
            head, frac = body.split(".", 1)
            frac = (frac + "000000")[:6]
            dt = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S")
            dt = dt.replace(microsecond=int(frac))
        else:
            dt = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# fiscal calendar                                                             #
# --------------------------------------------------------------------------- #

def quarter_of_date(d):
    return "%04dQ%d" % (d.year, (d.month - 1) // 3 + 1)


def quarter_of_instant(dt):
    return quarter_of_date(dt.date())


def quarter_of_iso(value):
    """Quarter of a stored ISO instant or date string."""
    return "%sQ%d" % (value[0:4], (int(value[5:7]) - 1) // 3 + 1)


def quarter_parts(q):
    return int(q[0:4]), int(q[5])


def quarter_end_date(q):
    year, num = quarter_parts(q)
    return {1: date(year, 3, 31), 2: date(year, 6, 30),
            3: date(year, 9, 30), 4: date(year, 12, 31)}[num]


def filing_deadline_date(q):
    return quarter_end_date(q) + timedelta(days=45)


def elapsed_quarters(from_q, to_q):
    fy, fn = quarter_parts(from_q)
    ty, tn = quarter_parts(to_q)
    return (ty - fy) * 4 + (tn - fn)


def quarter_shift(q, n):
    year, num = quarter_parts(q)
    total = year * 4 + (num - 1) + n
    return "%04dQ%d" % (total // 4, total % 4 + 1)


def current_quarter():
    return quarter_of_date(clock_date())
