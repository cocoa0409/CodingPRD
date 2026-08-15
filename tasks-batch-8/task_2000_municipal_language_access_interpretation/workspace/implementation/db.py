"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No entity is seeded at startup: every record is created through the declared
API surface by the tests themselves.
"""

COLLECTIONS = [
    "departments",
    "language_assessments",
    "vital_documents",
    "translation_jobs",
    "interpreters",
    "interpretation_requests",
    "complaints",
    "vendor_contracts",
    "language_access_plans",
]

db = {name: {} for name in COLLECTIONS}
