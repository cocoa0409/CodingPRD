"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts completely empty on every boot — no seeding of any kind.
Every entity any test needs is constructed through the declared API surface.
"""

COLLECTIONS = [
    "aid_years",
    "fund_types",
    "students",
    "isir_records",
    "verification_cases",
    "verification_documents",
    "conflicting_info_cases",
    "pj_cases",
    "award_packages",
    "award_lines",
    "award_notifications",
    "revision_requests",
    "disbursements",
    "overaward_cases",
    "external_aid",
    "reconciliation_runs",
    "reconciliation_adjustments",
]


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0  # global insertion counter: created_at tiebreak

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


db = Store()
