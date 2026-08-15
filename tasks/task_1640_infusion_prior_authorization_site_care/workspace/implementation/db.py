"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: every collection starts empty; tests construct all preconditions
through the declared API surface.
"""
import itertools

COLLECTIONS = [
    "payer_policies",
    "patients",
    "authorization_requests",
    "criteria_submissions",
    "appeals",
    "peer_to_peer_reviews",
    "site_of_care_determinations",
    "benefit_investigations",
    "financial_clearances",
    "responsibility_line_items",
    "infusion_chairs",
    "appointments",
    "dose_change_requests",
]

db = {name: {} for name in COLLECTIONS}

_seq_counter = itertools.count(1)


def next_seq() -> int:
    """Monotonic insertion sequence; stable tie-break for equal created_at."""
    return next(_seq_counter)


def touch(rec, now) -> None:
    """Every mutation increments version by exactly one and refreshes updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now
