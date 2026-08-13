"""In-memory data store (PRD §2.4, §2.5).

Storage is process-local dicts keyed by id. The store starts EMPTY on every
boot — no seeding of any kind. The logical clock defaults to exactly
2026-08-01T00:00:00Z before any explicit set (never the wall clock).
"""

import random
import uuid
from datetime import datetime, timezone

# --- Entity collections (keyed by resource id) ---
accounts = {}
transactions = {}
signers = {}
documents = {}
title_changes = {}
deceased_cases = {}
garnishments = {}
statement_cycles = {}
conversions = {}

# Monotonic creation counter — stable ascending creation order even when two
# resources are stamped within the same millisecond.
_creation_counter = [0]

# --- Logical clock (PRD §2.5) ---
_DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
_clock = {"current": _DEFAULT_CLOCK_ISO}


def new_uuid() -> str:
    return str(uuid.uuid4())


def next_creation_seq() -> int:
    _creation_counter[0] += 1
    return _creation_counter[0]


def now_timestamp() -> str:
    """Wall-clock ISO 8601 UTC with 3 fractional digits (created_at/updated_at)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def set_clock(to_iso8601: str) -> None:
    _clock["current"] = to_iso8601


def clock_instant() -> datetime:
    """Current logical instant (timezone-aware UTC)."""
    return parse_instant(_clock["current"])


def clock_date_str() -> str:
    """Current logical UTC calendar date as YYYY-MM-DD."""
    return clock_instant().strftime("%Y-%m-%d")


def parse_instant(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_used_account_numbers = set()


def mint_account_number() -> str:
    """Unique server-minted 10-digit account number (SCAFFOLD §1.1)."""
    while True:
        candidate = "".join(random.choices("0123456789", k=10))
        if candidate not in _used_account_numbers:
            _used_account_numbers.add(candidate)
            return candidate
