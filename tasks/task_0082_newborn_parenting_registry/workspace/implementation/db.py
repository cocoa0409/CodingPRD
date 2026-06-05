"""In-memory data store for the Newborn / Parenting Registry API.

The store starts EMPTY on every boot. Nothing is seeded, preloaded, or
hardcoded here — every entity any test needs is created by the test through
the declared API surface. The harness uses `--isolation per-test-server`, so a
fresh process (and therefore a fresh, empty store) backs every test.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional


def new_id() -> str:
    return str(uuid.uuid4())


# --- Tables: each keyed by id -> dict ---------------------------------------
pre_registrations: dict = {}
insurance_policies: dict = {}
newborns: dict = {}
lactation_consults: dict = {}
nicu_beds: dict = {}
nicu_stays: dict = {}
discharge_bags: dict = {}
follow_up_tasks: dict = {}
dependent_enrollments: dict = {}
government_filings: dict = {}
audit_events: dict = {}

# Monotonic creation sequence so that resources created within the same
# millisecond still sort deterministically by creation order.
_seq_counter: int = 0


def next_seq() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


# --- Test-driving clock (PRD §2.9) ------------------------------------------
# Pinned via POST /_clock/set_current_utc. None => use real wall clock.
_pinned_utc: Optional[str] = None


def set_clock(iso8601: str) -> None:
    global _pinned_utc
    _pinned_utc = iso8601


def current_utc_iso() -> str:
    if _pinned_utc is not None:
        return _pinned_utc
    return _wall_now_iso()


def current_utc_dt() -> datetime:
    return parse_iso(current_utc_iso())


def _wall_now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# --- ISO 8601 helpers -------------------------------------------------------
def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into a tz-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("Timestamp must be a string.")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError as e:
        raise ValueError(f"Invalid ISO 8601 timestamp: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s: str) -> datetime:
    """Parse an ISO 8601 calendar date (YYYY-MM-DD) into a tz-aware UTC dt."""
    if not isinstance(s, str):
        raise ValueError("Date must be a string.")
    txt = s.strip()
    try:
        d = datetime.strptime(txt, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"Invalid ISO 8601 date: {s}") from e
    return d.replace(tzinfo=timezone.utc)


def fmt_iso(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def dt_plus_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def dt_plus_hours(dt: datetime, hours: int) -> datetime:
    return dt + timedelta(hours=hours)


# --- Common-field helpers (PRD §2.4) ----------------------------------------
# id, created_at, updated_at, version. Timestamps are driven by the
# test-driving clock so that ordering is deterministic under a pinned clock.
def stamp_create(row: dict) -> None:
    now = current_utc_iso()
    row.setdefault("id", new_id())
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_seq"] = next_seq()


def stamp_update(row: dict) -> None:
    row["updated_at"] = current_utc_iso()
    row["version"] = int(row.get("version", 0)) + 1


def public(row: dict) -> dict:
    """Strip internal-only keys (those prefixed with '_') from a row."""
    return {k: v for k, v in row.items() if not k.startswith("_")}
