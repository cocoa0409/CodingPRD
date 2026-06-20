"""In-memory data store. Wiped on every fresh process boot — NO seeding.

Storage is plain Python dicts keyed by entity id. Each fresh boot starts every
collection empty; tests construct all required state through the declared API.
"""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone
from typing import Any, Dict


# ---- entity collections (one dict per entity, keyed by id) ------------------
communities: Dict[str, Dict[str, Any]] = {}
contract_plans: Dict[str, Dict[str, Any]] = {}
units: Dict[str, Dict[str, Any]] = {}
residents: Dict[str, Dict[str, Any]] = {}
residencies: Dict[str, Dict[str, Any]] = {}
second_persons: Dict[str, Dict[str, Any]] = {}
waitlist_entries: Dict[str, Dict[str, Any]] = {}
care_transitions: Dict[str, Dict[str, Any]] = {}
bed_reservations: Dict[str, Dict[str, Any]] = {}
monthly_invoices: Dict[str, Dict[str, Any]] = {}
refund_disbursements: Dict[str, Dict[str, Any]] = {}
councils: Dict[str, Dict[str, Any]] = {}
council_resolutions: Dict[str, Dict[str, Any]] = {}

# Tracks (resolution_id -> set of residency_ids that already voted), so a
# residency cannot vote twice on the same resolution.
resolution_votes: Dict[str, set] = {}


# Monotonic counter giving every created record a strict creation order. The PRD
# states created_at is minted with sub-millisecond uniqueness and is the
# canonical ordering key; this seq realizes that uniqueness deterministically.
_seq = itertools.count(1)


def next_seq() -> int:
    return next(_seq)


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


def now_iso() -> str:
    """ISO-8601 UTC timestamp with three fractional digits, suffix 'Z'."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
