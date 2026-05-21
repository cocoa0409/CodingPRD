"""Shared utilities: ID/serial minting, ISO 8601 formatting, time helpers."""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone
from typing import Optional


_ALPHANUM = string.ascii_uppercase + string.digits


def new_id() -> str:
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(_ALPHANUM, k=20))
    return f"req_{suffix}"


def new_pass_serial() -> str:
    return "".join(random.choices(_ALPHANUM, k=12))


def new_rank_seed() -> int:
    # Unsigned 64-bit pseudo-random seed.
    return random.randrange(0, 2**64)


def format_iso8601(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with three fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso8601(s: str) -> Optional[datetime]:
    """Lenient ISO 8601 parser; accepts trailing Z."""
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    if not s2:
        return None
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
