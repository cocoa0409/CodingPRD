"""Time / identifier helpers (PRD §2.4, §2.5, §2.8)."""

import re
import uuid
from datetime import datetime, timezone

from db import store
from errors import ApiError, ERR_INVALID_REQUEST

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def new_id():
    """UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits, 'Z' suffix."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % ms


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if not _ISO_RE.match(text):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' is not a valid ISO 8601 datetime" % field)
    t = text
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    # normalize offsets like +0000 -> +00:00
    if len(t) >= 5 and (t[-5] in "+-") and t[-3] != ":":
        t = t[:-2] + ":" + t[-2:]
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_of(value, field="datetime"):
    """Parse then re-format into canonical form."""
    return fmt_dt(parse_dt(value, field))


def clock_now():
    return store.clock.now()


def clock_iso():
    return fmt_dt(store.clock.now())
