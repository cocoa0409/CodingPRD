"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts completely empty: no seeding of any kind. Every entity a test
needs is built through the declared API surface.
"""

COLLECTIONS = [
    "programs",
    "employees",
    "allowance_policies",
    "assignments",
    "compensation_packages",
    "payroll_splits",
    "shadow_payroll_records",
    "settlements",
    "vendor_engagements",
    "certificates_of_coverage",
    "cost_projections",
    "extension_requests",
    "chargeback_entries",
]

db = {name: {} for name in COLLECTIONS}
