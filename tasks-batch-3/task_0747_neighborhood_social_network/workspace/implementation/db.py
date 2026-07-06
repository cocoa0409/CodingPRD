"""In-memory data store. Store starts empty on every boot."""
from __future__ import annotations

import uuid

from clock import CLOCK, iso_format


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        # keyed by id
        self.neighborhoods: dict[str, dict] = {}
        self.residents: dict[str, dict] = {}
        self.verification_requests: dict[str, dict] = {}
        self.resident_memberships: dict[str, dict] = {}
        self.posts: dict[str, dict] = {}
        self.marketplace_listings: dict[str, dict] = {}
        self.incidents: dict[str, dict] = {}
        self.civic_notices: dict[str, dict] = {}
        self.flag_reports: dict[str, dict] = {}
        self.moderation_decisions: dict[str, dict] = {}
        self.businesses: dict[str, dict] = {}
        self.local_ads: dict[str, dict] = {}
        self.groups: dict[str, dict] = {}
        self.events: dict[str, dict] = {}
        self.event_rsvps: dict[str, dict] = {}


DB = Store()


_SEQ = [0]
_INSERT_ORDER: dict[str, int] = {}


def _next_seq() -> int:
    _SEQ[0] += 1
    return _SEQ[0]


def insert_order_of(entity_id: str) -> int:
    """Insertion-order tiebreak for two rows sharing a `created_at`.

    PRD §2.8: "the row's `id` as a strictly tie-breaking ordering key that
    never on its own decides an observable outcome". When the deterministic-
    replay trust-score computation encounters two rows at the same logical-
    clock instant (e.g. an UPHOLD and a subsequent REVERSE stamped inside one
    server-side operation window), we tiebreak on this monotonic counter so
    causal server-side order — not UUID lexical order — decides pairing.
    """
    return _INSERT_ORDER.get(entity_id, 0)


def stamp_new(entity: dict) -> dict:
    """Set common fields on a freshly created entity."""
    now = iso_format(CLOCK.now())
    entity.setdefault("id", new_id())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    _INSERT_ORDER[entity["id"]] = _next_seq()
    return entity


def bump(entity: dict) -> dict:
    """Refresh updated_at and increment version by 1."""
    entity["updated_at"] = iso_format(CLOCK.now())
    entity["version"] = entity.get("version", 1) + 1
    return entity
