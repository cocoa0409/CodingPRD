"""In-memory data store, logical clock, id/version/timestamp bookkeeping.

Storage is process-local Python dicts only.  Nothing is seeded at import or at
boot: every entity in the system is created by clients through the declared
endpoints.
"""
import itertools
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction

# PRD 2.5 -- before any client sets it the logical clock reads exactly this.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or return None."""
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
        # Tolerate a bare date such as 2026-08-01.
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(dt):
    """Calendar date only, for the PRD's date-valued `..._on` fields."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def date_floor(dt):
    """Midnight of the instant's calendar date (the 'logical clock's date')."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.institutions = {}
        self.target_markets = {}
        self.cert_apps = {}
        self.board_seats = {}
        self.borrowers = {}
        self.loan_products = {}
        self.loans = {}
        self.ta_engagements = {}
        self.impact_reports = {}
        self.measurements = {}
        self.awards = {}
        self.commitments = {}
        self.clock = parse_dt(DEFAULT_CLOCK_ISO)
        self._seq = itertools.count(1)

    def seq(self):
        return next(self._seq)


db = Store()


def now():
    """The single server-side logical UTC instant."""
    return db.clock


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def base_row():
    """The four common properties every persisted resource carries (PRD 2.4)."""
    stamp = fmt_dt(now())
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.seq(),
    }


def touch(row, bump=1):
    """Refresh updated_at and advance version -- direct writes and cascades alike."""
    row["updated_at"] = fmt_dt(now())
    row["version"] = row["version"] + bump
    return row


def sort_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def ordered(rows):
    return sorted(rows, key=sort_key)


def public(row):
    """Strip internal keys and render Decimal/Fraction values as JSON numbers."""
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = _jsonify(value)
    return out


def _jsonify(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Fraction):
        return float(value)
    if isinstance(value, list):
        return [_jsonify(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonify(v) for k, v in value.items()}
    return value


EIN_RE = re.compile(r"^\d{9}$")
