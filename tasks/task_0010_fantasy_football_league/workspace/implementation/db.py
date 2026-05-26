"""In-memory data store. Starts empty on every boot.

Every entity is keyed by a UUID string. We also expose helpers for UUID
generation, timestamp generation, and request-id generation.
"""
from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone
from threading import RLock


# ---------------- ID / timestamp helpers ----------------

_CLOCK_OVERRIDE = {"value": None}  # ISO string when set, else None


def _format_ts(dt: datetime) -> str:
    """Return ISO 8601 UTC with three fractional digits and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Truncate to milliseconds
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def now_iso() -> str:
    """Return current UTC timestamp as ISO 8601 with ms precision.

    If a test-driving clock override is set, return that instead.
    """
    if _CLOCK_OVERRIDE["value"] is not None:
        return _CLOCK_OVERRIDE["value"]
    return _format_ts(datetime.now(timezone.utc))


def set_clock(iso_str: str) -> str:
    """Test-driving: set the server's current logical UTC clock."""
    # Normalize input — accept trailing Z and reformat to canonical with ms.
    normalized = _normalize_iso(iso_str)
    _CLOCK_OVERRIDE["value"] = normalized
    return normalized


def _normalize_iso(iso_str: str) -> str:
    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # last resort: try without microseconds
        dt = datetime.fromisoformat(s.split(".")[0] + "+00:00")
    return _format_ts(dt)


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ---------------- Data store ----------------

# A single global lock to serialize all mutating endpoints. Per-test-server
# isolation means concurrency-correctness here is mostly a courtesy.
_LOCK = RLock()


class DataStore:
    """In-memory store. All entities keyed by UUID string."""

    def __init__(self):
        # entity-name -> { id -> row dict }
        self.leagues: dict[str, dict] = {}
        self.teams: dict[str, dict] = {}
        self.players: dict[str, dict] = {}
        self.draft_picks: dict[str, dict] = {}
        self.roster_slots: dict[str, dict] = {}
        self.waiver_claims: dict[str, dict] = {}
        self.trades: dict[str, dict] = {}
        self.veto_votes: dict[str, dict] = {}
        self.matchups: dict[str, dict] = {}
        # Monotonic counter for created_at tiebreak fallback — appended to
        # each row as `_seq` (private; never serialized).
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


_STORE = DataStore()


def store() -> DataStore:
    return _STORE


def reset_store():
    """Reset the in-memory store (used by tests that boot a fresh server)."""
    global _STORE
    _STORE = DataStore()
    _CLOCK_OVERRIDE["value"] = None


def get_lock() -> RLock:
    return _LOCK
