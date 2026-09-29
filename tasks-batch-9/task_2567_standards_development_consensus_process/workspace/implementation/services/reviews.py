"""Public review counters, disposition bubbling and calendar occupancy (PRD 3.6).

The public review calendar is closed-inclusive: duration_days is the day
difference plus one, adjacency is forbidden by a symmetric 15-day buffer, and the
capacity of the buffered interval is exactly one.
"""

import datetime as _dt

from core.store import touch
from core.util import inclusive_days, pct1

from . import graph

DISPOSED_COMMENT_STATES = ("ACCEPTED", "ACCEPTED_WITH_MODIFICATION", "REJECTED")
OCCUPANT_STATES = ("OPEN", "CLOSED", "DISPOSITION_DRAFTED", "DISPOSITION_APPROVED")
BUFFER_DAYS = 15
MIN_REVIEW_DAYS = 45


def duration_days(start_date, end_date):
    return inclusive_days(start_date, end_date)


def recompute_counters(review):
    """Conserved ledger: disposed_count + unresolved_comment_count == comment_count."""
    comments = graph.comments_of_review(review)
    comment_count = len(comments)
    disposed_count = len([c for c in comments if c["status"] in DISPOSED_COMMENT_STATES])
    unresolved_comment_count = comment_count - disposed_count
    if comment_count == 0:
        completeness = 100.0
    else:
        completeness = pct1(disposed_count, comment_count)
    before = (review.get("comment_count"), review.get("disposed_count"),
              review.get("unresolved_comment_count"),
              review.get("disposition_completeness_pct"))
    review["comment_count"] = comment_count
    review["disposed_count"] = disposed_count
    review["unresolved_comment_count"] = unresolved_comment_count
    review["disposition_completeness_pct"] = completeness
    after = (review["comment_count"], review["disposed_count"],
             review["unresolved_comment_count"],
             review["disposition_completeness_pct"])
    return before != after


def bubble_disposition(review):
    """CLOSED -> DISPOSITION_DRAFTED once every comment is disposed, and the
    reverse edge when a REOPENED comment reintroduces an open item."""
    changed = False
    if (review["status"] == "CLOSED" and review["comment_count"] >= 1
            and review["unresolved_comment_count"] == 0):
        review["status"] = "DISPOSITION_DRAFTED"
        changed = True
    elif (review["status"] == "DISPOSITION_DRAFTED"
            and review["unresolved_comment_count"] > 0):
        review["status"] = "CLOSED"
        changed = True
    return changed


def refresh(review):
    """Recompute counters, apply the bubble edge, and version the review once."""
    changed = recompute_counters(review)
    if bubble_disposition(review):
        changed = True
    if changed:
        touch(review)
    return changed


def occupants_of_work_item(work_item, exclude_ids=()):
    """Reviews reachable through every draft of the work item that hold calendar
    space. SCHEDULED and CANCELLED reviews are not occupants."""
    out = []
    for review in graph.reviews_of_work_item(work_item):
        if review["id"] in exclude_ids:
            continue
        if review["status"] in OCCUPANT_STATES:
            out.append(review)
    return out


def buffer_conflict(work_item, start_date, end_date):
    """A candidate window conflicts when it comes within 15 days of an occupant
    on either side. Returns the first colliding occupant, or None."""
    delta = _dt.timedelta(days=BUFFER_DAYS)
    for occupant in occupants_of_work_item(work_item):
        occ_start = occupant["_start_date"]
        occ_end = occupant["_end_date"]
        if start_date <= occ_end + delta and occ_start <= end_date + delta:
            return occupant
    return None
