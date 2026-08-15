"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No entity is seeded at startup: every record is created through the declared
API surface by the tests themselves.
"""

COLLECTIONS = [
    "patients",
    "referral_orders",
    "authorizations",
    "beds",
    "technologists",
    "scorers",
    "physicians",
    "staffing_assignments",
    "sleep_studies",
    "scoring_tasks",
    "interpretation_reports",
    "therapy_prescriptions",
    "dme_orders",
    "inter_rater_cases",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence — stable tie-break for created_at-ascending
# sorts (the logical clock frequently stamps several records identically).
_seq_counter = {"value": 0}


def next_seq() -> int:
    _seq_counter["value"] += 1
    return _seq_counter["value"]
