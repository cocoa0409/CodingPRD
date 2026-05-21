"""Utility helpers — IDs, time formatting, request IDs."""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone

_ALPHANUM = string.ascii_letters + string.digits


def new_uuid() -> str:
    """Server-minted UUID (no type prefix)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Generate a request id like req_<20 char alphanum>."""
    body = "".join(secrets.choice(_ALPHANUM) for _ in range(20))
    return f"req_{body}"


def format_iso8601(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits and trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


def parse_iso8601(value):
    """Parse an ISO 8601 timestamp; accepts trailing Z or explicit offsets."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
