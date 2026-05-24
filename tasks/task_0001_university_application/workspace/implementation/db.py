"""In-memory data store.

Every collection starts empty on process boot. No seeding. No external
persistence. Tests are responsible for constructing every entity via the
declared API surface.
"""

from threading import RLock


# Each store is a dict keyed by entity id (uuid string)
applicants = {}
recommenders = {}
schools = {}
applications = {}
essay_submissions = {}
recommendation_letters = {}
financial_aid_profiles = {}
aid_offers = {}
admission_cycles = {}

# Single mutex used to serialize all state-mutating operations.
# Flask's default dev server is single-threaded, but we keep this for safety.
lock = RLock()
