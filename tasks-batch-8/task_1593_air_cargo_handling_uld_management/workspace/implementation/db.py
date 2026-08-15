"""In-memory data store for the Air Cargo ULD Management API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. The logical clock (PRD 2.5) also lives here.
"""

import uuid

from timeutil import DEFAULT_CLOCK_UTC, parse_instant, render_instant


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

flights: dict = {}
bookings: dict = {}
uld_types: dict = {}
ulds: dict = {}
build_up_plans: dict = {}
dg_declarations: dict = {}
temperature_logs: dict = {}
customs_holds: dict = {}
claims: dict = {}
uld_charges: dict = {}


# Monotonic insertion sequence: stable tie-break for created_at ordering when
# several rows are stamped at the same logical instant.
_seq = 0


def next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

_clock_literal: str = DEFAULT_CLOCK_UTC
_clock_instant = parse_instant(DEFAULT_CLOCK_UTC)


def clock_literal() -> str:
    """The exact string to report as current_utc from the clock endpoint."""
    return _clock_literal


def clock_now():
    """The current logical instant as a timezone-aware datetime."""
    return _clock_instant


def set_clock(literal: str, instant) -> None:
    global _clock_literal, _clock_instant
    _clock_literal = literal
    _clock_instant = instant


def now_iso() -> str:
    """The current logical instant rendered as a server stamp (rule i)."""
    return render_instant(_clock_instant)


# ---------------------------------------------------------------------------
# Entity stamping helpers
# ---------------------------------------------------------------------------

def stamp_new(entity: dict) -> dict:
    """Full common-field set (PRD 2.4): id, created_at, updated_at, version."""
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def stamp_new_light(entity: dict) -> dict:
    """ULDType / TemperatureLog: id + created_at only, no updated_at/version."""
    entity["id"] = new_id()
    entity["created_at"] = now_iso()
    entity["_seq"] = next_seq()
    return entity


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on a mutated entity (PRD 2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
