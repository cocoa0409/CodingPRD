"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: the store starts completely empty; the only initial state is the
logical clock default (see util.CLOCK).
"""
import itertools

COLLECTIONS = [
    "auditable_entities",
    "risk_assessments",
    "rating_criteria_configs",
    "audit_plans",
    "engagements",
    "auditors",
    "engagement_assignments",
    "workpapers",
    "findings",
    "management_responses",
    "action_plans",
    "extension_requests",
    "audit_reports",
    "qa_reviews",
    "committee_packs",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic insertion sequence for deterministic created_at tie-breaking.
_seq_counter = itertools.count(1)


def next_seq() -> int:
    return next(_seq_counter)
