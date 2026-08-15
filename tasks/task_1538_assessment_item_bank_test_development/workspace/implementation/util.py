"""Shared helpers: ids, timestamps, datetime parsing, program logical clock."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits (created_at/updated_at)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Program logical clock
# ---------------------------------------------------------------------------

CLOCK_DEFAULT = "2026-08-01T00:00:00Z"


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 datetime (accepts trailing Z), normalized to UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """Program-clock style: whole seconds, Z suffix."""
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def is_valid_datetime(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        parse_dt(s)
        return True
    except (ValueError, TypeError):
        return False


def program_clock(program) -> datetime:
    return program["_clock_dt"]


def program_clock_iso(program) -> str:
    return fmt_dt(program["_clock_dt"])


def advance_program_clock(program, by_seconds: int):
    program["_clock_dt"] = program["_clock_dt"] + timedelta(seconds=by_seconds)
    program["current_period_utc"] = fmt_dt(program["_clock_dt"])
