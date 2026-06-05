"""assign_cleaner selector per scaffold §1.3 / PRD §3.3.

Eligibility: Cleaner.status == ACTIVE AND postal_code in service_postal_codes.
Preferred subset: candidates that the customer has a PreferredPro row for.
pool = preferred if non-empty else candidates.
Ranking (entity fields only, never id):
  1. PreferredPro.priority ASC  (only when pool is the preferred subset)
  2. average_rating DESC (rating_sum/rating_count; 0 when count==0; exact ratio)
  3. completed_job_count DESC
  4. created_at ASC (tie-break; never id)
Empty pool -> ERR_NO_CLEANER_AVAILABLE.

Pinned-cleaner variant is handled by the caller (booking creation):
  - pin not ACTIVE -> ERR_CLEANER_NOT_CLEARED
  - pin does not serve postal -> ERR_NO_CLEANER_AVAILABLE
"""
from fractions import Fraction

import db
from errors import err


def _avg_rating_ratio(cleaner_rec):
    count = cleaner_rec.get("rating_count", 0)
    if count == 0:
        return Fraction(0, 1)
    return Fraction(cleaner_rec.get("rating_sum", 0), count)


def select_cleaner(customer_id, postal_code):
    """Run the auto-assignment selector. Returns the chosen cleaner record.

    Raises ERR_NO_CLEANER_AVAILABLE when the pool is empty.
    """
    candidates = [
        c for c in db.cleaners.values()
        if c.get("status") == "ACTIVE"
        and postal_code in (c.get("service_postal_codes") or [])
    ]
    if not candidates:
        raise err("ERR_NO_CLEANER_AVAILABLE", "no ACTIVE cleaner serves the area")

    # Customer's preferred pros: cleaner_id -> priority.
    pref_by_cleaner = {}
    for p in db.preferred_pros.values():
        if p.get("customer_id") == customer_id:
            pref_by_cleaner[p.get("cleaner_id")] = p.get("priority")

    preferred = [c for c in candidates if c["id"] in pref_by_cleaner]
    use_preferred = bool(preferred)
    pool = preferred if use_preferred else candidates

    def sort_key(c):
        priority = pref_by_cleaner.get(c["id"], 0) if use_preferred else 0
        avg = _avg_rating_ratio(c)
        completed = c.get("completed_job_count", 0)
        seq = c.get("_seq", 0)
        # priority ASC; avg DESC; completed DESC; created_at(seq) ASC.
        return (priority, -avg, -completed, seq)

    pool_sorted = sorted(pool, key=sort_key)
    return pool_sorted[0]
