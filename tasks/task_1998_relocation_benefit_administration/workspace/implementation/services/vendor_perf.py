"""Vendor performance aggregates per scaffold `vendor_performance_score`.

rating_sum, rating_count: across all rated MoveAssignments of this vendor.
avg_rating_lifetime: rating_sum / rating_count, 2dp half-up; null when no ratings.
avg_rating_rolling_12m: same quotient over assignments with rated_at >= clock - 12 months
                        (inclusive boundary); null when none in window.
"""

from datetime import timedelta

from db import DB
from util import round_half_up_two, add_months


def recompute_vendor(vendor_id):
    vendor = DB.vendors.get(vendor_id)
    if vendor is None:
        return
    assignments = [
        a for a in DB.move_assignments.values()
        if a["vendor_id"] == vendor_id and a.get("rating") is not None
    ]
    rating_sum = sum(a["rating"] for a in assignments)
    rating_count = len(assignments)
    vendor["rating_sum"] = rating_sum
    vendor["rating_count"] = rating_count
    if rating_count > 0:
        vendor["avg_rating_lifetime"] = round_half_up_two(rating_sum / rating_count)
    else:
        vendor["avg_rating_lifetime"] = None

    window_start = add_months(DB.now(), -12)
    in_window = [
        a for a in assignments
        if a.get("rated_at") is not None and a["rated_at"] >= window_start
    ]
    if in_window:
        s = sum(a["rating"] for a in in_window)
        vendor["avg_rating_rolling_12m"] = round_half_up_two(s / len(in_window))
    else:
        vendor["avg_rating_rolling_12m"] = None
