"""In-memory data store plus the logical clock.

The store is a plain set of dicts keyed by identifier.  It starts EMPTY on every
boot: nothing is seeded, preloaded or hardcoded.  Every entity is created
through the declared endpoints.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------- #
# collections                                                                 #
# --------------------------------------------------------------------------- #
advertisers = {}
publishers = {}
methodology_versions = {}
campaigns = {}
inventory_lists = {}
list_entries = {}
pre_bid_segments = {}
pages = {}
page_classifications = {}
appeals = {}
measurement_batches = {}
ivt_findings = {}
refund_claims = {}

COLLECTIONS = {
    "advertisers": advertisers,
    "publishers": publishers,
    "methodology_versions": methodology_versions,
    "campaigns": campaigns,
    "inventory_lists": inventory_lists,
    "list_entries": list_entries,
    "pre_bid_segments": pre_bid_segments,
    "pages": pages,
    "page_classifications": page_classifications,
    "appeals": appeals,
    "measurement_batches": measurement_batches,
    "ivt_findings": ivt_findings,
    "refund_claims": refund_claims,
}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- #
# logical clock                                                               #
# --------------------------------------------------------------------------- #
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_EPOCH}


def clock_now():
    """The single source of truth for time.  Never wall-clock."""
    return _clock["now"]


def clock_set(value):
    _clock["now"] = value
    return _clock["now"]


def parse_dt(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def now_iso():
    return fmt_dt(clock_now())


def days(count):
    return timedelta(days=count)


def seconds(count):
    return timedelta(seconds=count)


# --------------------------------------------------------------------------- #
# record helpers                                                              #
# --------------------------------------------------------------------------- #
def _touched_set():
    from flask import g

    if not hasattr(g, "touched_ids"):
        g.touched_ids = set()
    return g.touched_ids


def new_record(extra=None, with_common=True):
    """Create a fresh record carrying the common system fields.

    version starts at 1.  The record is marked as already-touched for this
    request so that a cascade running later in the same request does not bump a
    record it has just created.
    """
    stamp = now_iso()
    record = {"id": new_id()}
    if with_common:
        record["created_at"] = stamp
        record["updated_at"] = stamp
        record["version"] = 1
    else:
        record["created_at"] = stamp
    record["_seq"] = next_seq()
    if extra:
        record.update(extra)
    _touched_set().add(record["id"])
    return record


def touch(record):
    """Refresh updated_at and increment version by exactly 1.

    Idempotent inside a single request: PRD section 2.10 states that every record a
    cascade touches has its updated_at refreshed and its version incremented by
    1 -- one increment per record per request, no matter how many hops of the
    cascade reach it.
    """
    if record is None:
        return record
    seen = _touched_set()
    if record["id"] in seen:
        record["updated_at"] = now_iso()
        return record
    seen.add(record["id"])
    record["updated_at"] = now_iso()
    record["version"] = int(record.get("version", 1)) + 1
    return record


def sort_key(record):
    return (record.get("created_at") or "", record.get("_seq") or 0)


def ordered(records):
    return sorted(records, key=sort_key)
