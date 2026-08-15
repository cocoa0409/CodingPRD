"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts empty on every boot. The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_clock_utc = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock():
    return _clock_utc


def set_clock(dt):
    global _clock_utc
    _clock_utc = dt


def today():
    """Logical clock's UTC date as a date object."""
    return _clock_utc.date()


# ---------------------------------------------------------------------------
# Entity stores — plain dicts keyed by id
# ---------------------------------------------------------------------------
school_sites = {}
students = {}
sped_plans = {}
screening_cycles = {}
cut_score_profiles = {}
gifted_cases = {}
measure_scores = {}
committee_reviews = {}
committee_votes = {}
service_placements = {}
re_evaluations = {}
