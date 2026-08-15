"""In-memory data store. Fresh on every process boot (per-test-server isolation).

The store starts EMPTY on every boot — no seeding. Every entity a test needs is
constructed via the declared API surface.
"""

COLLECTIONS = [
    "branches",
    "representatives",
    "inspections",
    "findings",
    "correspondence_items",
    "outside_activities",
    "complaints",
    "disclosure_events",
    "supervision_plans",
    "meetings",
    "attestations",
    "wsp_documents",
    "exam_requests",
]

db = {name: {} for name in COLLECTIONS}
