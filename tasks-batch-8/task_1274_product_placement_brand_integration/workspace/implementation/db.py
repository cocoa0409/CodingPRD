"""In-memory data store. Empty on every boot - no seeding."""
import uuid


def new_id():
    return str(uuid.uuid4())


# Entity stores, keyed by id.
brands = {}
briefs = {}
series = {}
episodes = {}
opportunities = {}
proposals = {}
contracts = {}
shipments = {}
continuity_records = {}
clearances = {}
airing_reports = {}
makegood_credits = {}
cross_promos = {}
disclosures = {}

# Logical clock (ISO8601 string); initial reading per PRD 2.5.
clock = {"current_utc": "2026-05-01T00:00:00Z"}
