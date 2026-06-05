"""In-memory data store.

The store starts empty on every boot. Tests build all preconditions via the
declared API surface — no seeding here. Per-test-server isolation re-launches
the process before every test, so process memory is the only state.
"""

import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# All tables keyed by id -> dict
elections: dict = {}
precincts: dict = {}
registrations: dict = {}
ballots: dict = {}
cure_cases: dict = {}
machines: dict = {}
machine_failures: dict = {}
early_vote_checkins: dict = {}
recount_cases: dict = {}

# Singleton simulated clock. None => fall back to wall clock.
_clock_utc = None  # type: ignore


def set_clock(iso8601: str) -> None:
    global _clock_utc
    _clock_utc = iso8601


def current_utc_iso() -> str:
    if _clock_utc is not None:
        return _clock_utc
    return now_iso()


# Common-field helpers ------------------------------------------------
def stamp_create_full(row: dict) -> None:
    """Audit-bearing entities: id, created_at, updated_at, version=1."""
    now = now_iso()
    row.setdefault("id", new_id())
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1


def stamp_create_light(row: dict) -> None:
    """Lightweight immutable entities (MachineFailure, EarlyVoteCheckIn):
    only id + created_at. No updated_at, no version."""
    row.setdefault("id", new_id())
    row["created_at"] = now_iso()


def stamp_update(row: dict) -> None:
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 0)) + 1
