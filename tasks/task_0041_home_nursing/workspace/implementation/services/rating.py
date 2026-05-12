"""Nurse rating aggregation per §1.3 nurse_rating_aggregate."""
from decimal import Decimal

import db
from services.constants import RATING_WINDOW_SIZE, RATING_FLOOR, RATING_CEIL
from services.util import round_half_up_decimals


def recompute_rating(nurse_id: str) -> None:
    """Recompute Nurse.rating: latest 50 ratings, mean to two decimals.

    Each completed order produces one rating sample:
      - If the order has an UPHOLD nurse-related complaint with non-zero rating_impact:
          5.0 + rating_impact
      - Else: 5.0
    Sort by ServiceRecord.completed_at DESC; tiebreak by Order.id DESC.
    """
    nurse = db.nurses.get(nurse_id)
    if nurse is None:
        return

    # Build samples for completed orders assigned to this nurse
    samples = []  # (completed_at, order_id, value)
    for order in db.orders.values():
        if order.get("status") != "COMPLETED":
            continue
        # Find the assigned nurse via ServiceRecord
        sr = _find_record_by_order(order["id"])
        if sr is None or sr.get("nurse_id") != nurse_id:
            continue
        completed_at = sr.get("completed_at")
        if not completed_at:
            continue
        # Find a RESOLVED nurse-related complaint with non-zero impact
        impact = 0.0
        impacted = False
        for complaint in db.complaints.values():
            if complaint.get("order_id") != order["id"]:
                continue
            if complaint.get("stage") != "RESOLVED":
                continue
            if complaint.get("routing") != "NURSE_RELATED":
                continue
            ri = complaint.get("rating_impact") or 0
            if float(ri) != 0.0:
                impact = float(ri)
                impacted = True
                break
        value = 5.0 + (impact if impacted else 0.0)
        samples.append((completed_at, order["id"], value))

    if not samples:
        nurse["rating"] = float(round_half_up_decimals(Decimal("5.00"), 2))
        return

    # Sort by completed_at DESC, then order_id DESC
    samples.sort(key=lambda s: (s[0], s[1]), reverse=True)
    samples = samples[:RATING_WINDOW_SIZE]
    total = Decimal(0)
    for _, _, v in samples:
        total += Decimal(str(v))
    mean = total / Decimal(len(samples))
    rounded = round_half_up_decimals(mean, 2)
    if rounded < Decimal(str(RATING_FLOOR)):
        rounded = Decimal(str(RATING_FLOOR))
    if rounded > Decimal(str(RATING_CEIL)):
        rounded = Decimal(str(RATING_CEIL))
    nurse["rating"] = float(rounded)


def _find_record_by_order(order_id: str):
    for sr in db.service_records.values():
        if sr.get("order_id") == order_id:
            return sr
    return None


def apply_rating_impact_clamped(nurse_id: str, delta: float) -> None:
    """Clamp Nurse.rating to [1.00, 5.00] after adding delta. Persists to integer-cent
    rounding semantics with two decimals."""
    nurse = db.nurses.get(nurse_id)
    if nurse is None:
        return
    cur = Decimal(str(nurse.get("rating", 5.00)))
    new = cur + Decimal(str(delta))
    new = round_half_up_decimals(new, 2)
    if new < Decimal(str(RATING_FLOOR)):
        new = Decimal(str(RATING_FLOOR))
    if new > Decimal(str(RATING_CEIL)):
        new = Decimal(str(RATING_CEIL))
    nurse["rating"] = float(new)
    db.stamp_update(nurse)
