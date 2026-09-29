"""In-memory storage, the logical clock and shared numeric helpers.

Storage is a set of plain dicts keyed by id, insertion ordered, and it is
completely empty when the process boots: no entity data is ever seeded.
"""

import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from flask import g

UTC = timezone.utc

# PRD 2.4 - before any clock-setting call the logical clock reads exactly this.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------- collections
programs = {}
job_families = {}
channels = {}
personas = {}
signals = {}
postings = {}
flights = {}
applications = {}
touchpoints = {}
members = {}
campaigns = {}
sends = {}
reviews = {}
presences = {}
ledger = {}

ALL_COLLECTIONS = [
    programs, job_families, channels, personas, signals, postings, flights,
    applications, touchpoints, members, campaigns, sends, reviews, presences,
    ledger,
]

_runtime = {"clock": DEFAULT_CLOCK, "last_wall": None}


def reset():
    for coll in ALL_COLLECTIONS:
        coll.clear()
    _runtime["clock"] = DEFAULT_CLOCK
    _runtime["last_wall"] = None


# ---------------------------------------------------------------------- ids
def new_id():
    """Server-minted id: a bare UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_token():
    return uuid.uuid4().hex


# -------------------------------------------------------------------- clocks
def clock():
    """The logical clock - never the host wall clock."""
    return _runtime["clock"]


def set_clock(instant):
    _runtime["clock"] = instant


def wall_now():
    """Strictly increasing creation instant, so created_at is unique per row."""
    now = datetime.now(UTC)
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    last = _runtime["last_wall"]
    if last is not None and now <= last:
        now = last + timedelta(milliseconds=1)
    _runtime["last_wall"] = now
    return now


# ---------------------------------------------------------------- formatting
def fmt(instant):
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    instant = instant.astimezone(UTC)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def parse_instant(raw):
    """Parse an ISO 8601 instant; returns None when unparseable."""
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
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_day(raw):
    """Parse a YYYY-MM-DD calendar day; returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def day_midnight(raw):
    """The instant of a stored YYYY-MM-DD day at T00:00:00Z."""
    return parse_day(raw)


# ------------------------------------------------------------ mutation audit
def _request_bag(key):
    try:
        bag = getattr(g, key, None)
    except RuntimeError:
        return None
    if bag is None:
        bag = set()
        setattr(g, key, bag)
    return bag


def touch(entity):
    """Refresh updated_at and advance version by exactly 1, once per request."""
    if entity is None:
        return
    seen = _request_bag("_touched")
    if seen is not None:
        if entity["id"] in seen:
            entity["updated_at"] = wall_now()
            return
        seen.add(entity["id"])
    entity["updated_at"] = wall_now()
    entity["version"] = entity.get("version", 1) + 1


def mark_throttled(channel_id):
    bag = _request_bag("_throttled")
    if bag is not None:
        bag.add(channel_id)


def was_throttled(channel_id):
    bag = _request_bag("_throttled")
    return bool(bag) and channel_id in bag


# ------------------------------------------------------------------ rounding
def rhu(value):
    """round_half_up of an exact Fraction to an integer."""
    frac = Fraction(value)
    return (2 * frac.numerator + frac.denominator) // (2 * frac.denominator)


def flr(value):
    """floor of an exact Fraction to an integer."""
    return math.floor(Fraction(value))


def money2(value):
    """Round a Decimal half up to two places."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def largest_remainder(rows, total_bp=10000):
    """Floor-then-largest-remainder distribution of total_bp (PRD 2.5).

    `rows` is a list of (key, exact_share_as_Fraction) already in tie-break
    order; returns {key: awarded_bp}.
    """
    floors = {}
    fracs = []
    for index, (key, exact) in enumerate(rows):
        base = flr(exact)
        floors[key] = base
        fracs.append((exact - base, index, key))
    shortfall = total_bp - sum(floors.values())
    if shortfall > 0:
        fracs.sort(key=lambda item: (-item[0], item[1]))
        for _, _, key in fracs[:shortfall]:
            floors[key] += 1
    return floors
