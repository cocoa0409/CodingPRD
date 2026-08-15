"""Shared domain helpers: aggregates, cascades, lookup utilities."""

from datetime import date

import db
from errors import ApiError, ERR_NOT_ASSIGNED_REVIEWER


# ---------------------------------------------------------------------------
# Aggregate counts (computed fields)
# ---------------------------------------------------------------------------

def reviewer_active_count(reviewer_id):
    return sum(
        1 for a in db.assignments.values()
        if a["reviewer_id"] == reviewer_id and a["status"] == "ACTIVE"
    )


def engagement_unresolved_comment_count(engagement_id):
    return sum(
        1 for c in db.comments.values()
        if c["engagement_id"] == engagement_id
        and c["status"] in ("OPEN", "ADDRESSED", "REOPENED")
    )


def engagement_deferred_pending_count(engagement_id):
    return sum(
        1 for d in db.deferred_submittals.values()
        if d["engagement_id"] == engagement_id
        and d["status"] in ("REGISTERED", "SUBMITTED", "REJECTED")
    )


def refresh_engagement_counts(engagement):
    engagement["unresolved_comment_count"] = engagement_unresolved_comment_count(engagement["id"])
    engagement["deferred_pending_count"] = engagement_deferred_pending_count(engagement["id"])


def refresh_reviewer_count(reviewer):
    reviewer["active_assignment_count"] = reviewer_active_count(reviewer["id"])


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def active_assignment_for_cycle(cycle_id):
    for a in db.assignments.values():
        if a["cycle_id"] == cycle_id and a["status"] == "ACTIVE":
            return a
    return None


def record_for_engagement(engagement_id):
    for r in db.records.values():
        if r["engagement_id"] == engagement_id:
            return r
    return None


def current_nonterminal_cycle(engagement_id):
    """The engagement's current non-terminal cycle: the latest-created cycle
    whose status is not terminal (APPROVED/SUPERSEDED/CANCELLED)."""
    cands = [
        c for c in db.cycles.values()
        if c["engagement_id"] == engagement_id
        and c["status"] in ("OPEN", "IN_REVIEW", "COMMENTS_ISSUED")
    ]
    if not cands:
        return None
    cands.sort(key=lambda c: (c["created_at"], c["cycle_number"]))
    return cands[-1]


def require_assigned_reviewer(cycle, caller_uid):
    """Caller must be the reviewer on the given cycle's ACTIVE assignment."""
    a = active_assignment_for_cycle(cycle["id"])
    if a is None or a["reviewer_id"] != caller_uid:
        raise ApiError(
            ERR_NOT_ASSIGNED_REVIEWER, 403,
            "Caller is not the reviewer on this cycle's ACTIVE assignment",
        )
    return a


# ---------------------------------------------------------------------------
# License helpers
# ---------------------------------------------------------------------------

def license_for_state(reviewer, state_code):
    """Return the reviewer's license covering state_code, or None."""
    for lic in reviewer.get("licenses", []):
        if lic.get("state_code") == state_code:
            return lic
    return None


def parse_date(s):
    """Parse a YYYY-MM-DD date string."""
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def end_assignment(assignment, new_status):
    """ACTIVE -> COMPLETED|RELEASED with ended_at stamp and reviewer count
    decrement (via aggregate refresh)."""
    assignment["status"] = new_status
    assignment["ended_at"] = db.clock_now()
    db.touch(assignment)
    reviewer = db.reviewers.get(assignment["reviewer_id"])
    if reviewer is not None:
        refresh_reviewer_count(reviewer)
        db.touch(reviewer)


def complete_active_assignments(cycle):
    """Cycle APPROVED/SUPERSEDED: ACTIVE assignments -> COMPLETED."""
    for a in list(db.assignments.values()):
        if a["cycle_id"] == cycle["id"] and a["status"] == "ACTIVE":
            end_assignment(a, "COMPLETED")


def release_active_assignments(cycle):
    """Cycle CANCELLED: ACTIVE assignments -> RELEASED."""
    for a in list(db.assignments.values()):
        if a["cycle_id"] == cycle["id"] and a["status"] == "ACTIVE":
            end_assignment(a, "RELEASED")
