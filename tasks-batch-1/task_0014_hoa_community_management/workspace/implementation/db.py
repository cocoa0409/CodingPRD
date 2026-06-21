"""In-memory data store. Starts empty on every boot."""
from __future__ import annotations

import datetime
import uuid


# Global wall clock (PRD §2.5). One clock shared by all Communities.
# Initialized to the real wall clock on module load (i.e. server boot).
_current_utc: datetime.datetime = datetime.datetime.now(datetime.timezone.utc)


def get_current_utc() -> datetime.datetime:
    return _current_utc


def set_current_utc(dt: datetime.datetime):
    global _current_utc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    _current_utc = dt


# Entity stores keyed by id
communities: dict[str, dict] = {}
owners: dict[str, dict] = {}
properties: dict[str, dict] = {}
assessments: dict[str, dict] = {}
payment_applications: dict[str, dict] = {}
violations: dict[str, dict] = {}
acc_requests: dict[str, dict] = {}
board_elections: dict[str, dict] = {}
votes: dict[str, dict] = {}
liens: dict[str, dict] = {}
reserve_studies: dict[str, dict] = {}
reserve_components: dict[str, dict] = {}


def new_id() -> str:
    return str(uuid.uuid4())


def iso_now() -> str:
    """Return current_utc as ISO 8601 UTC with three fractional digits."""
    return fmt_iso(get_current_utc())


def fmt_iso(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime.datetime:
    """Parse ISO 8601 string, supporting both 'Z' and explicit offsets."""
    if not isinstance(s, str):
        raise ValueError("expected ISO 8601 string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt


def make_common_fields() -> dict:
    """Return common fields (id, created_at, updated_at, version) using current_utc."""
    now_s = iso_now()
    return {
        "id": new_id(),
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }


def bump(entity: dict):
    """Bump updated_at and version for an entity that has those fields."""
    entity["updated_at"] = iso_now()
    entity["version"] = int(entity.get("version", 1)) + 1
