"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No entity is seeded or preloaded at startup; every record is created through the
declared API surface.
"""

COLLECTIONS = [
    "funding_cycles",
    "eligible_services",
    "applicants",
    "nslp_snapshots",
    "applicant_users",
    "service_providers",
    "procurement_postings",
    "bids",
    "contracts",
    "funding_requests",
    "funding_request_lines",
    "invoice_submissions",
    "service_substitutions",
    "appeals",
    "retained_documents",
]

db = {name: {} for name in COLLECTIONS}
