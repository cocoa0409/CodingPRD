"""In-memory data store, the logical clock and row bookkeeping.

The store starts completely empty on every boot; nothing is seeded, preloaded
or hardcoded.  Every row a test needs is built through the declared API.
"""

import itertools
import random
import re
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# --------------------------------------------------------------------------
# Collections.  One dict per resource family, keyed by id.
# --------------------------------------------------------------------------
outings = {}
contracts = {}
package_tiers = {}
registrations = {}
players = {}
teams = {}
sponsorship_assets = {}
sponsor_allocations = {}
contests = {}
fundraising_items = {}
receipts = {}

COLLECTIONS = {
    "Outing": outings,
    "CourseContract": contracts,
    "PackageTier": package_tiers,
    "Registration": registrations,
    "Player": players,
    "Team": teams,
    "SponsorshipAsset": sponsorship_assets,
    "SponsorAllocation": sponsor_allocations,
    "Contest": contests,
    "FundraisingItem": fundraising_items,
    "CharitableReceipt": receipts,
}

_seq = itertools.count(1)
_lock = threading.RLock()

# --------------------------------------------------------------------------
# Logical clock.  Fixed default, never falls back to wall-clock time.
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00.000Z"

_clock = {"now": DEFAULT_CLOCK}

_TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?Z$")


def is_iso_utc(value):
    if not isinstance(value, str):
        return False
    if not _TS_RE.match(value):
        return False
    try:
        parse_ts(value)
    except Exception:
        return False
    return True


def parse_ts(value):
    """Parse an ISO-8601 UTC timestamp with a trailing Z into an aware datetime."""
    m = _TS_RE.match(value)
    if not m:
        raise ValueError("not an ISO 8601 UTC timestamp: %r" % (value,))
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    return datetime(
        int(m.group(1)), int(m.group(2)), int(m.group(3)),
        int(m.group(4)), int(m.group(5)), int(m.group(6)),
        micro, tzinfo=timezone.utc,
    )


def fmt_ts(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def canon_ts(value):
    """Canonicalise a client supplied timestamp to the three-digit wire format."""
    return fmt_ts(parse_ts(value))


def now_iso():
    return _clock["now"]


def now_dt():
    return parse_ts(_clock["now"])


def set_clock(value):
    _clock["now"] = canon_ts(value)


def reset_clock():
    _clock["now"] = DEFAULT_CLOCK


def minutes(n):
    return timedelta(minutes=n)


def days(n):
    return timedelta(days=n)


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def new_row(kind, fields, common=True):
    """Create a row.  `version` starts at 1; created/updated stamp the clock."""
    row = dict(fields)
    row["id"] = new_id()
    row["_kind"] = kind
    row["_seq"] = next(_seq)
    stamp = now_iso()
    row["created_at"] = stamp
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    COLLECTIONS[kind][row["id"]] = row
    _touched().add((kind, row["id"]))
    return row


def _touched():
    s = getattr(g, "_touched_rows", None)
    if s is None:
        s = set()
        g._touched_rows = s
    return s


def touch(row):
    """Bump version/updated_at at most once per request for this row."""
    if row is None:
        return
    key = (row["_kind"], row["id"])
    seen = _touched()
    if key in seen:
        return
    seen.add(key)
    if "version" in row:
        row["version"] = row.get("version", 1) + 1
        row["updated_at"] = now_iso()


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def reset_all():
    for coll in COLLECTIONS.values():
        coll.clear()
    reset_clock()
