"""Waitlist ranking helpers.

Ranking rule (§3.7 / SCAFFOLD): 1-based, ordered by waitlist_added_at ASC,
with created_at ASC as the deterministic tie-breaker. The id field is never
used as a sort key.
"""

import db


def recompute_waitlist_ranks(school_id: str) -> None:
    """Renumber waitlist_rank for every WAITLISTED app at this school."""
    waitlisted = [
        app
        for app in db.applications.values()
        if app["school_id"] == school_id and app["status"] == "WAITLISTED"
    ]
    waitlisted.sort(key=lambda a: (a["waitlist_added_at"], a["created_at"]))
    for idx, app in enumerate(waitlisted, start=1):
        app["waitlist_rank"] = idx


def clear_rank(application_row) -> None:
    application_row["waitlist_rank"] = None
