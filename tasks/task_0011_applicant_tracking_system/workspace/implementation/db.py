"""In-memory data store.

Each entity is stored in its own dict keyed by id. The store starts empty
on every process boot — tests construct all required state via the public
API surface.
"""
from threading import RLock


lock = RLock()

departments = {}            # id -> dict
requisitions = {}
candidates = {}
applications = {}
interviews = {}
interview_feedback = {}     # id -> dict (append-only)
offers = {}
background_checks = {}
referral_bonuses = {}
diversity_goals = {}


def reset() -> None:
    """Clear all stores. Useful for tests that explicitly wipe state."""
    for store in (
        departments,
        requisitions,
        candidates,
        applications,
        interviews,
        interview_feedback,
        offers,
        background_checks,
        referral_bonuses,
        diversity_goals,
    ):
        store.clear()
