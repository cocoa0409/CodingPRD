"""In-memory data store. Fresh on every process boot (per-test-server isolation).
The store starts empty; no entity is ever seeded at startup."""

COLLECTIONS = [
    "physicians",
    "comp_plans",
    "cpt_rates",
    "physician_agreements",
    "production_captures",
    "supervision_assignments",
    "quality_scorecards",
    "comp_statements",
    "true_up_runs",
    "disputes",
    "plan_change_requests",
]

db = {name: {} for name in COLLECTIONS}
