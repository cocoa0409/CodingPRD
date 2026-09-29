"""In-memory data store, id/timestamp minting and the logical clock.

The store starts completely empty on every boot.  Nothing is seeded, preloaded,
registered or hardcoded here: every row in every table is created by an API
caller through the endpoints declared in the PRD.
"""

import itertools
import random
import string
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Table names (one per persisted resource in PRD Section 2.4)
# ---------------------------------------------------------------------------
AGENCY = "agency"
STATE_PROGRAM = "state_program"
APPOINTMENT = "agency_appointment"
CPL = "closing_protection_letter"
POLICY_FILE = "policy_file"
STATEMENT = "remittance_statement"
LINE = "remittance_line"
ESCROW_ACCOUNT = "escrow_account"
ESCROW_AUDIT = "escrow_audit"
FINDING = "audit_finding"
CLAIM = "agency_claim"

KINDS = [
    AGENCY,
    STATE_PROGRAM,
    APPOINTMENT,
    CPL,
    POLICY_FILE,
    STATEMENT,
    LINE,
    ESCROW_ACCOUNT,
    ESCROW_AUDIT,
    FINDING,
    CLAIM,
]

# PRD 2.4: "Before any client sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z -- a fixed server startup default, never a fallback to
# real wall-clock time."
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

request_lock = threading.RLock()


class Store(object):
    def __init__(self):
        self.tables = dict((k, {}) for k in KINDS)
        self.seq = itertools.count(1)
        self.current_utc = CLOCK_DEFAULT
        self._last_ts = None

    # -- tables ---------------------------------------------------------
    def table(self, kind):
        return self.tables[kind]

    def get(self, kind, row_id):
        if not isinstance(row_id, str):
            return None
        return self.tables[kind].get(row_id)

    def all(self, kind):
        """Every row of a kind in ascending created_at order."""
        return sorted(self.tables[kind].values(), key=lambda r: r["_seq"])

    def where(self, kind, **eq):
        out = []
        for row in self.all(kind):
            if all(row.get(k) == v for k, v in eq.items()):
                out.append(row)
        return out

    # -- minting --------------------------------------------------------
    def next_seq(self):
        return next(self.seq)

    def real_now(self):
        """Strictly increasing wall-clock instant used for created_at/updated_at."""
        now = datetime.now(timezone.utc)
        if self._last_ts is not None and now <= self._last_ts:
            now = self._last_ts + timedelta(microseconds=1000)
        self._last_ts = now
        return now


store = Store()


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------
def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso_ms(store.real_now())


def clock_instant():
    """The logical clock instant, formatted like every other timestamp."""
    return iso_ms(store.current_utc)


def clock_date():
    """The calendar date of the logical clock instant in UTC (PRD 2.4)."""
    return store.current_utc.astimezone(timezone.utc).date()


def parse_date(value):
    """Strict YYYY-MM-DD, returns a date or None when unparseable."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_datetime(value):
    if not isinstance(value, str):
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


def date_str(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


def days_between(start, end):
    """Whole calendar days from start to end (PRD 2.5: whole-day arithmetic)."""
    return (end - start).days


# ---------------------------------------------------------------------------
# row minting / serialisation
# ---------------------------------------------------------------------------
def new_row(kind, fields):
    row_id = str(uuid.uuid4())
    created = now_iso()
    row = {"id": row_id}
    row.update(fields)
    row["created_at"] = created
    row["updated_at"] = created
    row["version"] = 1
    row["_seq"] = store.next_seq()
    store.tables[kind][row_id] = row
    return row


def serialize(row):
    if isinstance(row, list):
        return [serialize(r) for r in row]
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))
