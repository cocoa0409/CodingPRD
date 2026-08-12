"""In-memory data store. Empty on every boot; nothing is seeded or persisted."""

import itertools

TABLES = (
    "specialty_tracks",
    "referring_providers",
    "specialists",
    "panel_memberships",
    "consult_requests",
    "consult_responses",
    "clarification_messages",
    "in_person_conversions",
    "quality_reviews",
    "compensation_entries",
    "availability_windows",
    "billing_claims",
    "avoided_visit_measurements",
    "routing_decisions",
)

store = {name: {} for name in TABLES}

_seq_counter = itertools.count(1)


def next_seq():
    """Global monotonic insertion sequence; stable tie-break under created_at."""
    return next(_seq_counter)
