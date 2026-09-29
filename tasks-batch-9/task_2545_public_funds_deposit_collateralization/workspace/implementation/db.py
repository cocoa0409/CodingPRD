"""In-memory data store, logical clock and timestamp plumbing.

The store starts completely empty on every boot: nothing in this module (or in
any module it imports) seeds, preloads or hardcodes an entity. Every record is
created only by an explicit API call.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from constants import DEFAULT_CLOCK_UTC, OPEN_ENDED_SENTINEL

# ---------------------------------------------------------------------------
# Collections. Keyed by record id; insertion order preserved.
# ---------------------------------------------------------------------------
COLLECTIONS = (
    "custodians",
    "pooled_programs",
    "public_units",
    "depositories",
    "qualification_reviews",
    "deposit_accounts",
    "pledge_agreements",
    "collateral_assets",
    "pledge_allocations",
    "substitution_requests",
    "mtm_runs",
    "margin_calls",
    "safekeeping_receipts",
    "runoff_forecasts",
)

store = {name: {} for name in COLLECTIONS}

LOCK = threading.RLock()

_state = {"seq": 0}


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_iso(moment):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


class Ts(object):
    """A timestamp carrying both its comparable instant and its rendering.

    Server-minted stamps render in the canonical three-fractional-digit form.
    Client-supplied instants are echoed back exactly as they were supplied, and
    the open-ended pledge sentinel renders as the literal instant named by the
    PRD.
    """

    __slots__ = ("dt", "text")

    def __init__(self, dt, text):
        self.dt = dt
        self.text = text

    @classmethod
    def system(cls, moment):
        return cls(moment, format_iso(moment))

    @classmethod
    def of(cls, raw):
        parsed = parse_iso(raw)
        if parsed is None:
            return None
        return cls(parsed, raw.strip())

    def plus_hours(self, hours):
        return Ts.system(self.dt + timedelta(hours=hours))

    def __eq__(self, other):
        if not isinstance(other, Ts):
            return NotImplemented
        return self.dt == other.dt and self.text == other.text

    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    def __hash__(self):
        return hash((self.dt, self.text))

    def __repr__(self):
        return "Ts(%s)" % self.text


SENTINEL_TS = Ts(parse_iso(OPEN_ENDED_SENTINEL), OPEN_ENDED_SENTINEL)

_clock = {"now": parse_iso(DEFAULT_CLOCK_UTC)}


def clock():
    """The current logical clock instant."""
    return _clock["now"]


def set_clock(moment):
    _clock["now"] = moment


def now_ts():
    return Ts.system(_clock["now"])


def now_text():
    return format_iso(_clock["now"])


def hours_between(earlier, later):
    return (later - earlier).total_seconds() / 3600.0


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_record(fields, versioned=True):
    """Build a record: server-minted id, the supplied domain fields, then the
    audit stamps of PRD 2.4. MarkToMarketRun passes versioned=False because it
    carries only id and created_at."""
    stamp = now_ts()
    record = {"id": new_id()}
    record.update(fields)
    record["created_at"] = stamp
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    record["_seq"] = next_seq()
    return record


def insert(collection, record):
    store[collection][record["id"]] = record
    return record


def get(collection, record_id):
    if not isinstance(record_id, str):
        return None
    return store[collection].get(record_id)


def touch(record):
    """Refresh updated_at and bump version for an explicit mutation."""
    if "version" in record:
        record["updated_at"] = now_ts()
        record["version"] = record["version"] + 1
    return record


def rows(collection):
    """All records of a collection in default order (created_at ASC)."""
    return sorted(store[collection].values(), key=lambda r: (r["created_at"].dt, r["_seq"]))


def reset():
    for name in COLLECTIONS:
        store[name].clear()
    _clock["now"] = parse_iso(DEFAULT_CLOCK_UTC)
    _state["seq"] = 0
