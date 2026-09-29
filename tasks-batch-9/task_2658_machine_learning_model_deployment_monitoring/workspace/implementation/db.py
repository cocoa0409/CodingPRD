"""In-memory store, logical clock, id minting and serialisation helpers.

The store starts completely empty on every boot: no entity is ever seeded,
preloaded or hardcoded.  Every row is created by a caller through a declared
endpoint.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, getcontext

getcontext().prec = 60

UTC = timezone.utc

# PRD 2.4 / 3.9: the logical clock's startup default, never wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

TABLES = (
    "models",
    "training_datasets",
    "model_versions",
    "serving_endpoints",
    "deployments",
    "traffic_ramp_steps",
    "monitoring_windows",
    "drift_reports",
    "skew_checks",
    "retraining_triggers",
    "challenger_evaluations",
    "prediction_incidents",
    "revalidation_tasks",
)

store = {t: {} for t in TABLES}

_state = {"clock": CLOCK_DEFAULT, "seq": 0}


# --------------------------------------------------------------------------
# clock
# --------------------------------------------------------------------------
def now():
    return _state["clock"]


def set_clock(value):
    previous = _state["clock"]
    _state["clock"] = value
    return previous


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# datetime formatting / parsing
# --------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(raw):
    """Parse an ISO-8601 instant into an aware UTC datetime, or None."""
    if not isinstance(raw, str):
        return None
    m = _DT_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1000000))
    tzpart = m.group(8)
    offset = timedelta(0)
    if tzpart and tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        body = tzpart[1:].replace(":", "")
        offset = sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    return dt - offset


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(dt, days):
    """Whole days added, preserving the anchor's time-of-day exactly."""
    return dt + timedelta(days=int(days))


def whole_days_between(start, end):
    if start is None or end is None:
        return 0
    delta = end - start
    days = delta.days if delta.total_seconds() >= 0 else -((-delta).days + 1)
    return days


# --------------------------------------------------------------------------
# decimal helpers
# --------------------------------------------------------------------------
D0 = Decimal(0)


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def q2(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) + D0


def q4(value):
    out = dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if out == 0:
        out = Decimal("0.0000")
    return out


def trunc2(value):
    """Truncate toward zero at two decimals (PRD 2.5, degraded ramp halving)."""
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_DOWN) + D0


def dec_out(value):
    if value is None:
        return None
    f = float(value)
    if f == 0.0:
        return 0.0
    return f


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------
def insert(table, fields, common=True):
    row = {"id": new_id()}
    row.update(fields)
    instant = now()
    row["created_at"] = instant
    if common:
        row["updated_at"] = instant
        row["version"] = 1
    row["_seq"] = next_seq()
    store[table][row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return store[table].get(row_id)


def rows(table):
    return list(store[table].values())


def created_key(row):
    return (row["created_at"], row["_seq"])


def sorted_created(items):
    return sorted(items, key=created_key)


def _conv(value):
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, Decimal):
        return dec_out(value)
    if isinstance(value, dict):
        return {k: _conv(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_conv(v) for v in value]
    return value


def public(row):
    if row is None:
        return None
    return {k: _conv(v) for k, v in row.items() if not k.startswith("_")}
