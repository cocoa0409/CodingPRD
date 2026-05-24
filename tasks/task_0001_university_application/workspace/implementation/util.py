"""Shared helpers: id minting, timestamps, ISO parsing, server clock."""

import uuid
from datetime import datetime, timezone

import db


# --------------------------------------------------------------------------- #
# Identifiers and timestamps
# --------------------------------------------------------------------------- #

def new_id() -> str:
    """Server-minted UUID with no prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def server_clock_iso() -> str:
    """Return the current value of the global test clock.

    The global server clock is exposed per-school via AdmissionCycle.clock_iso
    (PRD §2.10) and is also held as a global value (the maximum of any explicit
    /_clock/advance + actual wall-clock time). For simplicity we keep a single
    global clock that can be advanced; entity timestamps and rule comparisons
    all read from the same global.
    """
    return _format_iso(_current_clock_dt())


def server_clock_dt() -> datetime:
    return _current_clock_dt()


# --------------------------------------------------------------------------- #
# Global clock state
# --------------------------------------------------------------------------- #

# The "anchor" is the last explicit clock value set via /_clock/advance.
# When the test clock is never advanced, we fall back to real UTC now.
_clock_state = {"anchor": None}  # datetime | None


def set_clock(target_dt: datetime) -> None:
    """Set the global clock to the given UTC datetime."""
    if target_dt.tzinfo is None:
        target_dt = target_dt.replace(tzinfo=timezone.utc)
    else:
        target_dt = target_dt.astimezone(timezone.utc)
    _clock_state["anchor"] = target_dt


def _current_clock_dt() -> datetime:
    anchor = _clock_state["anchor"]
    if anchor is not None:
        return anchor
    return datetime.now(timezone.utc)


def reset_clock() -> None:
    """Clear any explicit anchor (used for tests; not exposed via API)."""
    _clock_state["anchor"] = None


# --------------------------------------------------------------------------- #
# ISO 8601 helpers
# --------------------------------------------------------------------------- #

def _format_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def format_iso(dt):
    if dt is None:
        return None
    return _format_iso(dt)


def parse_iso(value):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime.

    Accepts:
      - 'Z' as UTC designator (PRD §2.9 requires UTC)
      - +HH:MM offset notation
      - No timezone designator (interpreted as UTC)
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Entity housekeeping
# --------------------------------------------------------------------------- #

def stamp_create(row: dict) -> dict:
    """Populate id/created_at/updated_at/version on a new entity row."""
    now = _current_clock_dt()
    row.setdefault("id", new_id())
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    return row


def stamp_update(row: dict) -> dict:
    """Bump updated_at and version on a mutated entity row."""
    row["updated_at"] = _current_clock_dt()
    row["version"] = int(row.get("version", 0)) + 1
    return row


# --------------------------------------------------------------------------- #
# Common-field serializer
# --------------------------------------------------------------------------- #

def common_fields(row: dict) -> dict:
    return {
        "id": row["id"],
        "created_at": format_iso(row["created_at"]),
        "updated_at": format_iso(row["updated_at"]),
        "version": row["version"],
    }
