from decimal import Decimal
from util import round_half_up


def pricing_tier_for(course, local_hour):
    if course["peak_start_hour"] <= local_hour < course["peak_end_hour"]:
        return "PEAK"
    return "OFF_PEAK"


def green_fee_cents(course, golfer, pricing_tier):
    base = course["peak_fee_cents"] if pricing_tier == "PEAK" else course["offpeak_fee_cents"]
    if golfer["membership_tier"] == "MEMBER":
        discount = round_half_up(Decimal(base) * Decimal(str(course["member_discount_pct"])), 0)
        return int(base) - int(discount)
    return int(base)


def standby_bookings(tee_time_id, db):
    return [
        b for b in db.bookings.values()
        if b["tee_time_id"] == tee_time_id and b["status"] == "STANDBY"
    ]


def _priority_key(booking, db):
    golfer = db.golfers[booking["golfer_id"]]
    membership_rank = 0 if golfer["membership_tier"] == "MEMBER" else 1
    return (membership_rank, booking["created_at"])


def rerank_standby(tee_time_id, db):
    """Recompute standby_rank (1-based) for all STANDBY bookings on the slot."""
    sb = standby_bookings(tee_time_id, db)
    sb_sorted = sorted(sb, key=lambda b: _priority_key(b, db))
    for i, b in enumerate(sb_sorted, start=1):
        b["standby_rank"] = i


def select_promotion(tee_time_id, db):
    """Return the highest-priority STANDBY booking to promote, or None."""
    sb = standby_bookings(tee_time_id, db)
    if not sb:
        return None
    return min(sb, key=lambda b: _priority_key(b, db))
