"""In-memory data store. Each entity has its own dict keyed by id."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .clock import CLOCK


# A single big lock is enough for correctness — each request is short-lived.
LOCK = threading.RLock()


class Store:
    def __init__(self) -> None:
        # entity_name -> { id -> dict }
        self.tournaments: dict[str, dict[str, Any]] = {}
        self.team_registrations: dict[str, dict[str, Any]] = {}
        self.player_contracts: dict[str, dict[str, Any]] = {}
        self.identity_verifications: dict[str, dict[str, Any]] = {}
        self.matches: dict[str, dict[str, Any]] = {}
        self.draft_events: dict[str, dict[str, Any]] = {}
        self.match_incidents: dict[str, dict[str, Any]] = {}
        # contract_id -> list of amendment dicts; amendments are tracked as side records
        self.amendments: dict[str, dict[str, Any]] = {}
        self.referees: dict[str, dict[str, Any]] = {}
        self.crowdfund_contributions: dict[str, dict[str, Any]] = {}
        self.prize_payouts: dict[str, dict[str, Any]] = {}
        self.transfer_offers: dict[str, dict[str, Any]] = {}
        self.transfer_windows: dict[str, dict[str, Any]] = {}
        self.audit_logs: dict[str, dict[str, Any]] = {}

        # team_id -> {"risk": int, "last_decay_at": datetime}
        self.team_risk: dict[str, dict[str, Any]] = {}

        # match_id -> snapshot list used during disqualification cascade reversal
        # Key: incident_id -> { "match_snapshots": [...], "registration_status": "REGISTERED", "payout_snapshots": [...], "risk_delta": int }
        self.cascade_history: dict[str, dict[str, Any]] = {}

        # Track ruled_at for appeal-window calc
        self.ruled_at: dict[str, Any] = {}

        # Concurrency uniqueness tracking
        # (match_id, subject_id, classification) -> incident_id
        self.incident_uniq: dict[tuple, str] = {}
        # (match_id, step_index) -> draft_event_id (only counts non-anomaly + tracked steps)
        self.draft_step_uniq: dict[tuple, str] = {}


_STORE = Store()


def get_store() -> Store:
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = Store()
    CLOCK.reset()


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    from .clock import format_iso
    return format_iso(CLOCK.now)  # type: ignore[return-value]


def common_fields_create() -> dict[str, Any]:
    """Returns id + created_at + updated_at + version=1 fields."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def common_fields_append_only() -> dict[str, Any]:
    """Returns id + created_at only (for immutable rows)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def bump_version(entity: dict[str, Any]) -> None:
    if "version" in entity:
        entity["version"] = int(entity.get("version", 1)) + 1
    entity["updated_at"] = now_iso()
