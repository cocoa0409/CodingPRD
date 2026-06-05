"""Half-open [pickup_at, dropoff_at) interval overlap helpers."""
from util import parse_iso8601


def overlaps(res_a, res_b):
    """True iff two reservations' [pickup_at, dropoff_at) intervals overlap.

    Half-open semantics: a shared boundary instant does NOT count as overlap.
    i.e. a.start < b.end AND b.start < a.end.
    """
    a_start = parse_iso8601(res_a["pickup_at"])
    a_end = parse_iso8601(res_a["dropoff_at"])
    b_start = parse_iso8601(res_b["pickup_at"])
    b_end = parse_iso8601(res_b["dropoff_at"])
    return a_start < b_end and b_start < a_end
