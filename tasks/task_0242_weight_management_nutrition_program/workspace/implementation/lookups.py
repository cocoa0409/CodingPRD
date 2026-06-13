"""Entity lookups with type-specific not-found errors (PRD 2.5) and the
deterministic-clock instant parser."""
from datetime import datetime, timezone

from db import db
from errors import (
    ERR_ASSIGNMENT_NOT_FOUND,
    ERR_COACH_NOT_FOUND,
    ERR_ELIGIBILITY_NOT_FOUND,
    ERR_ENROLLMENT_NOT_FOUND,
    ERR_GOAL_NOT_FOUND,
    ERR_INTAKE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND,
    ERR_MILESTONE_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_RX_NOT_FOUND,
    ERR_THREAD_NOT_FOUND,
    raise_error,
)


def _find(coll, ident, err):
    if not isinstance(ident, str) or ident not in coll:
        raise_error(err, "Resource not found")
    return coll[ident]


def get_program(ident):
    return _find(db.programs, ident, ERR_PROGRAM_NOT_FOUND)


def get_plan(ident):
    return _find(db.plans, ident, ERR_PLAN_NOT_FOUND)


def get_member(ident):
    return _find(db.members, ident, ERR_MEMBER_NOT_FOUND)


def get_coach(ident):
    return _find(db.coaches, ident, ERR_COACH_NOT_FOUND)


def get_intake(ident):
    return _find(db.intake_assessments, ident, ERR_INTAKE_NOT_FOUND)


def get_enrollment(ident):
    return _find(db.enrollments, ident, ERR_ENROLLMENT_NOT_FOUND)


def get_goal(ident):
    return _find(db.goals, ident, ERR_GOAL_NOT_FOUND)


def get_milestone(ident):
    return _find(db.milestones, ident, ERR_MILESTONE_NOT_FOUND)


def get_assignment(ident):
    return _find(db.coach_assignments, ident, ERR_ASSIGNMENT_NOT_FOUND)


def get_thread(ident):
    return _find(db.message_threads, ident, ERR_THREAD_NOT_FOUND)


def get_message(ident):
    # No dedicated message not-found error exists in the PRD catalogue;
    # surface a generic 404 (thread-not-found is the nearest cataloged 404
    # within the messaging subtree).
    if not isinstance(ident, str) or ident not in db.messages:
        raise_error(ERR_THREAD_NOT_FOUND, "Message not found")
    return db.messages[ident]


def get_invoice(ident):
    return _find(db.invoices, ident, ERR_INVOICE_NOT_FOUND)


def get_eligibility(ident):
    return _find(db.eligibility_determinations, ident, ERR_ELIGIBILITY_NOT_FOUND)


def get_rx(ident):
    return _find(db.rx_authorizations, ident, ERR_RX_NOT_FOUND)


# --- deterministic clock instant parsing ---
def parse_instant(value, field="to_iso8601"):
    """Parse an ISO 8601 instant into epoch seconds (float). Reject malformed."""
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 string")
    s = value
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def iso_from_seconds(seconds):
    """Format epoch seconds back to ISO 8601 UTC with 3 fractional digits."""
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def program_clock_seconds(program):
    return parse_instant(program["current_utc"], "current_utc")
