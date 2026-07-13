"""In-memory data store, logical clock, and shared primitives.

Every boot starts with a completely empty store. No entity is ever seeded or
preloaded here; tests build all preconditions through the declared API surface.
"""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): startup default is exactly 2026-03-01T00:00:00Z and
# the server NEVER falls back to wall-clock time for domain computations.
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


def get_now():
    return _CLOCK["now"]


def set_now(dt):
    _CLOCK["now"] = dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Monotonic insertion sequence — used as a stable secondary sort key so that
# rows created at the same logical-clock instant list in creation order.
# ---------------------------------------------------------------------------
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Data collections (dicts keyed by id, except repeat_callers keyed by caller_key)
# ---------------------------------------------------------------------------
contacts = {}
screenings = {}
safety_plans = {}
teams = {}
dispatches = {}
centers = {}
referrals = {}
followups = {}
emergencies = {}
repeat_callers = {}  # keyed by caller_key


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    """Parse an ISO-8601 instant into an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str) or not s.strip():
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Serialize an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def delta_ms(later, earlier):
    d = later - earlier
    return d.days * 86400000 + d.seconds * 1000 + d.microseconds // 1000


def round_half_up(value, ndigits=0):
    """Round using ROUND_HALF_UP. Returns int when ndigits==0 else float."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = Decimal(1).scaleb(-ndigits)  # 10^-ndigits
    r = d.quantize(q, rounding=ROUND_HALF_UP)
    if ndigits == 0:
        return int(r)
    return float(r)


# ---------------------------------------------------------------------------
# Mutation helper: version/updated_at bump on any actual field change (PRD 2.5).
# One call == one logical mutation == at most one version increment.
# ---------------------------------------------------------------------------
def mutate(entity, **changes):
    changed = False
    for k, v in changes.items():
        if entity.get(k) != v:
            entity[k] = v
            changed = True
    if changed and "version" in entity:
        entity["version"] += 1
        entity["updated_at"] = get_now()
    return changed


# ---------------------------------------------------------------------------
# Serialization: emit domain fields, converting datetimes; drop private keys.
# ---------------------------------------------------------------------------
def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = iso(v)
        else:
            out[k] = v
    return out
