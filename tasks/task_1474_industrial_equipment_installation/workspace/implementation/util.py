"""Time, id, and Decimal helpers."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now_iso():
    """Wall-clock timestamp for created_at/updated_at: ISO 8601 UTC, 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def D(v):
    return Decimal(str(v))


def round_half_up_int(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(d):
    """Decimal -> JSON-native int when integral, else float."""
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def parse_datetime(s):
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise ValueError("not a YYYY-MM-DD date")
    return datetime.strptime(s, "%Y-%m-%d").date()


def fmt_clock(dt):
    """Logical-clock display: ISO 8601 UTC with Z suffix."""
    return dt.isoformat().replace("+00:00", "Z")
