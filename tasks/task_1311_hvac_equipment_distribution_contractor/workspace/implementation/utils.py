"""Shared helpers: ids, timestamps (ISO 8601 UTC, 3 fractional digits), Decimal
parsing, rounding, structural payload validation."""
import calendar
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

import clock
from errors import ApiError, ERR_INVALID_REQUEST

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    return str(uuid.uuid4())


_seq_counter = {"n": 0}


def next_seq():
    """Monotonic insertion counter used to break created_at ties deterministically."""
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_request_id():
    return "req_" + uuid.uuid4().hex


def iso(dt):
    """Format an aware UTC datetime as ISO 8601 with exactly 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_datetime(value):
    """Parse an ISO 8601 datetime (date-only allowed -> midnight UTC). Returns
    aware UTC datetime or None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if _DATE_ONLY.match(s):
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return dt
        s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def parse_decimal(value):
    """Parse a JSON number into Decimal; returns None on failure.
    Booleans are rejected (they are not numbers for our purposes)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            return None
    return None


def round_half_up_cents(d):
    """Round a Decimal to whole cents (integer), half-up."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def quant2(d):
    """Quantize a Decimal to 2 decimal places (weights), half-up."""
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def dec_out(d, places="0.01"):
    """Serialize a Decimal as a JSON number with the given quantization."""
    if d is None:
        return None
    return float(d.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def add_months(dt, months):
    """Add whole months to a datetime, clamping the day to the target month."""
    idx = (dt.year * 12 + (dt.month - 1)) + months
    year, month0 = divmod(idx, 12)
    month = month0 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def touch(entity):
    """Mutation bookkeeping: refresh updated_at from the logical clock and
    increment version by exactly 1."""
    entity["updated_at"] = clock.now()
    entity["version"] = entity.get("version", 1) + 1


def now_iso():
    return iso(clock.now())


# ---------------------------------------------------------------------------
# Structural validation (priority 22 — deliberately evaluated LAST by callers)
# ---------------------------------------------------------------------------

class StructErrors:
    """Collects structural problems; raised after all business checks pass."""

    def __init__(self):
        self.problems = []

    def add(self, msg):
        self.problems.append(msg)

    @property
    def bad(self):
        return bool(self.problems)

    def raise_if_bad(self):
        if self.bad:
            raise ApiError(ERR_INVALID_REQUEST, 400, "; ".join(self.problems))


def check_unknown_fields(body, allowed, struct):
    for key in body:
        if key not in allowed:
            struct.add("Unknown field: %s" % key)


def get_required(body, field, struct):
    if field not in body or body[field] is None:
        struct.add("Missing required field: %s" % field)
        return None
    return body[field]


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def get_int(body, field, struct, required=True, minimum=None):
    if field not in body or body[field] is None:
        if required:
            struct.add("Missing required field: %s" % field)
        return None
    v = body[field]
    if not is_int(v):
        struct.add("Field %s must be an integer" % field)
        return None
    if minimum is not None and v < minimum:
        struct.add("Field %s must be >= %s" % (field, minimum))
        return None
    return v


def get_str(body, field, struct, required=True):
    if field not in body or body[field] is None:
        if required:
            struct.add("Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, str) or v == "":
        struct.add("Field %s must be a non-empty string" % field)
        return None
    return v


def get_enum(body, field, struct, values, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            struct.add("Missing required field: %s" % field)
        return default
    v = body[field]
    if v not in values:
        struct.add("Field %s must be one of %s" % (field, sorted(values)))
        return None
    return v


def get_decimal(body, field, struct, required=True):
    if field not in body or body[field] is None:
        if required:
            struct.add("Missing required field: %s" % field)
        return None
    d = parse_decimal(body[field])
    if d is None:
        struct.add("Field %s must be a number" % field)
        return None
    return d


def get_datetime(body, field, struct, required=True):
    if field not in body or body[field] is None:
        if required:
            struct.add("Missing required field: %s" % field)
        return None
    dt = parse_datetime(body[field])
    if dt is None:
        struct.add("Field %s must be an ISO 8601 datetime" % field)
        return None
    return dt


def period_window(period):
    """'2026-H1' -> [2026-01-01, 2026-07-01); '2026-H2' -> [2026-07-01, 2027-01-01)."""
    m = re.match(r"^(\d{4})-H([12])$", period or "")
    if not m:
        return None
    year = int(m.group(1))
    half = int(m.group(2))
    if half == 1:
        return (datetime(year, 1, 1, tzinfo=timezone.utc),
                datetime(year, 7, 1, tzinfo=timezone.utc))
    return (datetime(year, 7, 1, tzinfo=timezone.utc),
            datetime(year + 1, 1, 1, tzinfo=timezone.utc))
