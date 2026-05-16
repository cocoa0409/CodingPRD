"""In-memory data store with UUID minting + timestamp + version helpers.

All entities are keyed by their UUID strings.
"""

import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now_str() -> str:
    """Wall-clock UTC ISO 8601 with three fractional digits, Z suffix.

    Used for entity `created_at`/`updated_at` system fields.
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# Global stores keyed by primary id
DISTRICTS: dict = {}
STUDENTS: dict = {}
EVALUATIONS: dict = {}
CONSENTS: dict = {}
IEPS: dict = {}
GOALS: dict = {}
SERVICES: dict = {}
SESSIONS: dict = {}
TRANSITION_PLANS: dict = {}
PROGRESS_REPORTS: dict = {}


def stamp_create(entity: dict) -> None:
    """Set id, created_at, updated_at, version for a new entity."""
    if "id" not in entity:
        entity["id"] = new_id()
    ts = utc_now_str()
    entity.setdefault("created_at", ts)
    entity["updated_at"] = ts
    entity["version"] = 1


def stamp_update(entity: dict) -> None:
    """Refresh updated_at and bump version by one. No-op if absent."""
    entity["updated_at"] = utc_now_str()
    entity["version"] = entity.get("version", 1) + 1


def stamp_create_event(entity: dict) -> None:
    """Lightweight create for append-only event records (ParentalConsent, GoalProgressReport).

    No `updated_at`, no `version`. Only `id` and `created_at`.
    """
    if "id" not in entity:
        entity["id"] = new_id()
    entity.setdefault("created_at", utc_now_str())
