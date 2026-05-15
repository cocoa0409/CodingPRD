"""Simulated test clock and ISO 8601 utilities."""
import re
from datetime import datetime, timezone

from .errors import APIError
from .store import get_store


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(?:Z|([+-])(\d{2}):?(\d{2}))?$"
)


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 instant; raise ERR_VALIDATION on malformed input. Returns aware UTC datetime."""
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", "timestamp must be a string in ISO 8601 format")
    s = value.strip()
    # Accept fractional seconds of any reasonable length; normalize trailing Z.
    if s.endswith("Z"):
        s_norm = s[:-1] + "+00:00"
    else:
        s_norm = s
    try:
        dt = datetime.fromisoformat(s_norm)
    except ValueError as exc:
        raise APIError("ERR_VALIDATION", f"invalid timestamp: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_now_dt() -> datetime:
    return parse_iso(get_store().clock["now"])


def clock_now_iso() -> str:
    return get_store().clock["now"]


def set_clock(target_now: str) -> None:
    dt = parse_iso(target_now)
    get_store().clock["now"] = format_iso(dt)
