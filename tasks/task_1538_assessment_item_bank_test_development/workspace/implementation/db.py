"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: every collection starts empty; tests construct all state via the API.
"""

COLLECTIONS = [
    "assessment_programs",
    "content_standards",
    "items",
    "review_committees",
    "review_sessions",
    "review_verdicts",
    "field_test_windows",
    "item_responses",
    "item_statistics",
    "test_blueprints",
    "test_forms",
    "form_item_slots",
    "equating_links",
    "item_variants",
    "access_grants",
    "validity_dossiers",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic creation counter — deterministic tiebreaker for created_at sorting.
_seq = [0]


def next_seq() -> int:
    _seq[0] += 1
    return _seq[0]
