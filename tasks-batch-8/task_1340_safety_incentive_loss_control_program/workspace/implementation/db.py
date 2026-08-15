"""In-memory data store. The store starts empty on every boot; no seeding.

Every entity any caller needs is constructed through the declared API surface.
"""

import itertools

DB = {
    "programs": {},
    "job_roles": {},
    "training_courses": {},
    "employees": {},
    "training_assignments": {},
    "hazards": {},
    "controls": {},
    "observations": {},
    "meetings": {},
    "action_items": {},
    "contractors": {},
    "claims": {},
    "recommendations": {},
    "awards": {},
    "events": {},
    "forecasts": {},
}

_seq = itertools.count(1)


def next_seq():
    """Monotonic insertion sequence for stable created_at tie-breaking."""
    return next(_seq)
