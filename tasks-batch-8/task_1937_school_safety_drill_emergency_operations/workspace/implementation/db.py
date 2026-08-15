"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts empty — no seeding. Every entity is constructed via the API.
"""

COLLECTIONS = [
    "sites",
    "requirements",
    "eops",
    "site_plan_documents",
    "walkthroughs",
    "drill_events",
    "roster_entries",
    "after_action_reviews",
    "corrective_actions",
    "accommodation_plans",
    "compliance_reports",
]

db = {name: {} for name in COLLECTIONS}

_seq_counter = [0]


def next_seq() -> int:
    """Monotonic insertion sequence for deterministic ordering under tied timestamps."""
    _seq_counter[0] += 1
    return _seq_counter[0]
