"""In-memory data store + per-entity helpers.

A single Store instance owns all dictionaries. Entities are keyed by UUID
string. Common audit trio fields (created_at, updated_at, version) live on each
entity dict directly; AuditEvent is the only exception (no updated_at/version).
"""
from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, List, Optional

from .time_utils import now_iso


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self) -> None:
        self.seasons: Dict[str, dict] = {}
        self.players: Dict[str, dict] = {}
        self.guardians: Dict[str, dict] = {}
        self.teams: Dict[str, dict] = {}
        self.coaches: Dict[str, dict] = {}
        self.referees: Dict[str, dict] = {}
        self.games: Dict[str, dict] = {}
        self.shifts: Dict[str, dict] = {}
        self.audits: List[dict] = []
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ audit
    def record_audit(
        self,
        entity_type: str,
        entity_id: str,
        actor_role: Optional[str],
        actor_id: Optional[str],
        action: str,
        details: dict | None = None,
    ) -> dict:
        evt = {
            "id": new_id(),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "action": action,
            "details": details or {},
            "created_at": now_iso(),
        }
        self.audits.append(evt)
        return evt


_singleton: Store | None = None


def get_store() -> Store:
    global _singleton
    if _singleton is None:
        _singleton = Store()
    return _singleton


def reset_store() -> None:
    """Test-helper to clear state between containers; not exposed via HTTP."""
    global _singleton
    _singleton = Store()


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def stamp_create(entity: dict) -> dict:
    ts = now_iso()
    entity.setdefault("id", new_id())
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def stamp_update(entity: dict) -> dict:
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 0)) + 1
    return entity
