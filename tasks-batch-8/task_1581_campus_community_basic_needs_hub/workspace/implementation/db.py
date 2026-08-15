"""In-memory data store. Fresh on every process boot (per-test-server isolation).

No seeding: every collection starts empty; tests construct all entities via the
declared API surface.
"""
import itertools

COLLECTIONS = [
    "clients",
    "staff",
    "assessments",
    "pantry_items",
    "pantry_visits",
    "visit_line_items",
    "screenings",
    "grant_applications",
    "grant_funds",
    "shelter_beds",
    "shelter_stays",
    "partner_agencies",
    "referrals",
    "outreach_events",
    "event_registrations",
]

db = {name: {} for name in COLLECTIONS}

# Global monotonic insertion sequence; defines the deterministic creation order
# used for list sorting and tie-breaks (created_at ties under the logical clock).
SEQ = itertools.count(1)
