"""In-memory data store."""

import threading
import uuid
from datetime import datetime
from typing import Dict

from clock import clock
from response import format_iso


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Each table is a dict keyed by id.
        self.rights_holders: Dict[str, dict] = {}
        self.agency_bindings: Dict[str, dict] = {}
        self.works: Dict[str, dict] = {}
        self.rights_shares: Dict[str, dict] = {}
        self.share_change_audits: Dict[str, dict] = {}
        self.playback_batches: Dict[str, dict] = {}
        self.playback_events: Dict[str, dict] = {}
        self.distribution_rule_versions: Dict[str, dict] = {}
        self.royalty_pools: Dict[str, dict] = {}
        self.distributions: Dict[str, dict] = {}
        self.micro_balances: Dict[str, dict] = {}  # key: f"{holder_id}|{currency}"
        self.disputes: Dict[str, dict] = {}
        self.payout_batches: Dict[str, dict] = {}
        self.payments: Dict[str, dict] = {}
        self.external_sync_events: Dict[str, dict] = {}

        # source_identifier → pre-registered secret
        self.playback_source_secrets: Dict[str, str] = {}

        # holder lifetime paid (for dispute exposure score), keyed by holder id.
        self.holder_lifetime_paid_cents: Dict[str, int] = {}

        # Ordering counter for created_at ties when needed.
        self._created_counter = 0

    def gen_id(self) -> str:
        return str(uuid.uuid4())

    def now_iso(self) -> str:
        return format_iso(clock.now())

    def common_fields(self) -> dict:
        ts = self.now_iso()
        return {
            "id": self.gen_id(),
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }

    def lean_fields(self) -> dict:
        ts = self.now_iso()
        return {
            "id": self.gen_id(),
            "created_at": ts,
        }

    def touch(self, row: dict):
        """Bump version and refresh updated_at on a row with common fields."""
        if "version" in row:
            row["version"] = row.get("version", 1) + 1
        if "updated_at" in row:
            row["updated_at"] = self.now_iso()


store = Store()
