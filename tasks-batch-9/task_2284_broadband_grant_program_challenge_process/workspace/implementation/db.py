"""In-memory data store and logical clock.

The store starts completely empty on every boot.  Nothing is ever seeded,
preloaded or hardcoded here: every entity is created through the public API.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD section 2.3: the logical clock is initialised to a fixed epoch on boot.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.programs = {}
        self.locations = {}
        self.challenges = {}
        self.evidence = {}
        self.subgrantees = {}
        self.applications = {}
        self.claims = {}
        self.score_sheets = {}
        self.awards = {}
        self.env_reviews = {}
        self.milestones = {}
        self.ledger = {}
        self.audits = {}
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def now(self):
        return self.clock


db = Store()


# ---------------------------------------------------------------- timestamps

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    d = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        d.year, d.month, d.day, d.hour, d.minute, d.second, d.microsecond // 1000,
    )


def parse_ts(value):
    """Parse an ISO 8601 timestamp that carries an explicit UTC offset.

    Returns an aware datetime, or None when the value cannot be parsed.
    """
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
        return None
    return dt.astimezone(timezone.utc)


def now_ts():
    return fmt_ts(db.now())


def dt_of(stored):
    """Turn a stored timestamp string back into an aware datetime."""
    return parse_ts(stored)


# ------------------------------------------------------------------- records

def new_id():
    return str(uuid.uuid4())


def new_record(fields, versioned=True):
    """Build a record with the common system fields (PRD section 2.4)."""
    rec = {"id": new_id()}
    rec.update(fields)
    rec["created_at"] = now_ts()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def serialize(rec):
    return dict((k, v) for k, v in rec.items() if not k.startswith("_"))


def sort_rows(rows):
    """Default list ordering: created_at ascending (stable by insertion)."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
