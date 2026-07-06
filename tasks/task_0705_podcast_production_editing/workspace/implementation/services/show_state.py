"""Show derived-field recomputation (PRD §2.5).

production_posture (first match wins, fixed order):
  1. any Invoice DISPUTED            -> SUSPENDED
  2. else no ACTIVE EngagementContract -> SUSPENDED
  3. else any Invoice OVERDUE         -> ON_HOLD
  4. else                            -> ACTIVE

open_episode_count: count of this show's episodes whose status is NOT IN
{PUBLISHED, ARCHIVED, CANCELLED}.

Recomputing a derived field is itself a mutation (PRD §2.4): it refreshes
updated_at and bumps version on the show — but only when a value actually
changes, so an idempotent recompute that finds nothing to change does not
spuriously bump version.
"""
from db import db

_CLOSED_EPISODE_STATES = {"PUBLISHED", "ARCHIVED", "CANCELLED"}


def _invoices_for_show(show_id):
    return [i for i in db.invoices.all() if i["show_id"] == show_id]


def _contracts_for_show(show_id):
    return [c for c in db.contracts.all() if c["show_id"] == show_id]


def compute_posture(show_id):
    invoices = _invoices_for_show(show_id)
    contracts = _contracts_for_show(show_id)
    if any(i["status"] == "DISPUTED" for i in invoices):
        return "SUSPENDED"
    if not any(c["status"] == "ACTIVE" for c in contracts):
        return "SUSPENDED"
    if any(i["status"] == "OVERDUE" for i in invoices):
        return "ON_HOLD"
    return "ACTIVE"


def compute_open_episode_count(show_id):
    return sum(
        1
        for e in db.episodes.all()
        if e["show_id"] == show_id and e["status"] not in _CLOSED_EPISODE_STATES
    )


def recompute_posture(show):
    """Recompute posture; on change, mutate (bump version + updated_at)."""
    new_posture = compute_posture(show["id"])
    if show.get("production_posture") != new_posture:
        show["production_posture"] = new_posture
        db.shows.touch(show)


def recompute_open_episode_count(show):
    new_count = compute_open_episode_count(show["id"])
    if show.get("open_episode_count") != new_count:
        show["open_episode_count"] = new_count
        db.shows.touch(show)


def recompute_show(show):
    """Recompute both derived fields for a show."""
    recompute_open_episode_count(show)
    recompute_posture(show)
