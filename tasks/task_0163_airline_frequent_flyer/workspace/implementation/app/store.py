"""In-memory data store and ID generation."""

from __future__ import annotations

import threading
import uuid
from typing import Dict, Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


class DataStore:
    """Single in-memory store containing every entity dictionary, keyed by id."""

    def __init__(self) -> None:
        self.members: Dict[str, dict] = {}
        self.flights: Dict[str, dict] = {}
        self.segments: Dict[str, dict] = {}
        self.points_transactions: Dict[str, dict] = {}
        self.upgrade_requests: Dict[str, dict] = {}
        self.award_bookings: Dict[str, dict] = {}
        self.companion_certificates: Dict[str, dict] = {}
        self.status_match_requests: Dict[str, dict] = {}
        self.membership_years: Dict[str, dict] = {}

        # Per-(flight_id, cabin) monotonic waitlist sequence counter
        self.waitlist_seq_by_flight_cabin: Dict[tuple, int] = {}

        # Per-member case-insensitive email index
        self.member_email_index: Dict[str, str] = {}

        # Gift idempotency lookup: (member_id, idempotency_key) -> {payload_hash, transaction_ids}
        self.gift_idempotency: Dict[tuple, dict] = {}

        # Monotonic insertion sequence for tie-breaking ledger on equal posted_at/created_at
        self._ins_seq = 0

        # Global lock for serializing critical sections (in-memory only).
        self.lock = threading.RLock()

    def next_seq(self) -> int:
        self._ins_seq += 1
        return self._ins_seq


# Global store instance.
store = DataStore()
