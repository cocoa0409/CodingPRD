"""Storage-zone capacity check: peak coincident load over half-open intervals
(PRD §3.8)."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import db


def peak_load_exceeds(zone_id: str, start, end, cap_units, zone_capacity) -> bool:
    """Return True if adding the candidate booking [start, end) with cap_units
    pushes the peak coincident occupancy strictly above the zone capacity.

    Overlap is strict half-open: B.start < C.end AND C.start < B.end. The peak
    is evaluated at each distinct interval boundary point that lies within the
    candidate interval, summing the candidate plus every overlapping booking
    that covers that point. Comparison rounds half up to three decimals.
    """
    existing = [b for b in db.bookings.values() if b["zone_id"] == zone_id]

    overlapping = []
    for b in existing:
        b_start = b["_start_dt"]
        b_end = b["_end_dt"]
        if b_start < end and start < b_end:  # strict half-open overlap
            overlapping.append(b)

    if not overlapping:
        # The candidate alone occupies cap_units; only exceeds if it alone is
        # above capacity.
        cand = Decimal(str(cap_units)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        cap = Decimal(str(zone_capacity)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        return cand > cap

    # Candidate boundary points: candidate start plus every overlapping booking's
    # start that falls inside [start, end). At each sample point the load is the
    # candidate plus every overlapping booking covering that instant.
    sample_points = {start}
    for b in overlapping:
        if start <= b["_start_dt"] < end:
            sample_points.add(b["_start_dt"])

    cap = Decimal(str(zone_capacity)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    for p in sample_points:
        load = Decimal(str(cap_units))
        for b in overlapping:
            if b["_start_dt"] <= p < b["_end_dt"]:
                load += Decimal(str(b["capacity_units"]))
        load = load.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if load > cap:
            return True
    return False
