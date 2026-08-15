"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts empty on every boot — no seeding. Every entity any test needs
is constructed via the declared API surface.
"""

COLLECTIONS = [
    "pay_equity_studies",
    "employee_snapshots",
    "comparator_groups",
    "model_runs",
    "gap_findings",
    "remediation_plans",
    "adjustments",
    "report_filings",
    "jurisdiction_rules",
    "transparency_postings",
    "pipeline_analyses",
    "monitoring_cycles",
]

db = {name: {} for name in COLLECTIONS}

# Monotonic creation counter — stable tiebreaker for created_at-ascending sorts.
_seq = {"n": 0}


def next_seq() -> int:
    _seq["n"] += 1
    return _seq["n"]
