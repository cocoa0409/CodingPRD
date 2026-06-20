"""Eligibility posture computation (PRD 3.1).

Coverage lives in append-only EligibilitySpan rows. A span covers the half-open
interval [coverage_start, coverage_end). A member is eligible "now" iff some
non-voided span has coverage_start <= now < coverage_end.
"""
from clock import clock
from db import db
from helpers import parse_dt


def member_spans(member_id):
    return [s for s in db.eligibility_spans.values() if s["member_id"] == member_id]


def span_covers(span, instant):
    """True if a non-voided span covers `instant` under half-open [start, end)."""
    if span["voided"]:
        return False
    start = parse_dt(span["coverage_start"])
    end = parse_dt(span["coverage_end"])
    return start <= instant < end


def has_coverage_now(member_id):
    now = clock.now()
    return any(span_covers(s, now) for s in member_spans(member_id))


def covering_span_for(member_id, instant):
    """Return a non-voided span covering `instant`, or None."""
    for s in member_spans(member_id):
        if span_covers(s, instant):
            return s
    return None
