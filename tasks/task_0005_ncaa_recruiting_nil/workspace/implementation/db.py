"""In-memory data store.

The store starts empty on every boot. Tests build all preconditions via the
declared API surface — no seeding here.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# All tables keyed by id -> dict
programs: dict = {}
periods: dict = {}
student_athletes: dict = {}
eligibility_certifications: dict = {}
recruiting_contacts: dict = {}
scholarship_offers: dict = {}
nil_deals: dict = {}
transfer_portal_entries: dict = {}
booster_incidents: dict = {}

# NIL deal SoD ledger: deal_id -> set of X-User-IDs that submitted or
# requested-revision on this deal.
nil_actor_history: dict = {}


# System clock --------------------------------------------------------
# Pinned via POST /ncaa/_clock/set_current_utc. None = use real wall clock.
_pinned_utc: Optional[str] = None


def set_clock(iso8601: str) -> None:
    global _pinned_utc
    _pinned_utc = iso8601


def current_utc_iso() -> str:
    if _pinned_utc is not None:
        return _pinned_utc
    return now_iso()


def current_utc_dt() -> datetime:
    return parse_iso(current_utc_iso())


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into a tz-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("Timestamp must be a string.")
    txt = s.strip()
    # Accept trailing Z and convert to +00:00
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError as e:
        raise ValueError(f"Invalid ISO 8601 timestamp: {s}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_plus_days(iso: str, days: int) -> str:
    dt = parse_iso(iso) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Common-field helpers -----------------------------------------------
def stamp_create(row: dict) -> None:
    now = now_iso()
    row.setdefault("id", new_id())
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1


def stamp_update(row: dict) -> None:
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 0)) + 1


# Test-isolation reset: clear all in-memory state. Module import already
# starts empty, but tests that hit a singleton process via threaded restart
# can call this. (Not exposed via HTTP — the harness uses per-test server
# restart, so each boot is fresh.)
def _reset() -> None:
    programs.clear()
    periods.clear()
    student_athletes.clear()
    eligibility_certifications.clear()
    recruiting_contacts.clear()
    scholarship_offers.clear()
    nil_deals.clear()
    transfer_portal_entries.clear()
    booster_incidents.clear()
    nil_actor_history.clear()
    global _pinned_utc
    _pinned_utc = None
